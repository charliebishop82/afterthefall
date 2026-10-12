"""Disposable ledger and Bank ownership/replay checks."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from database.create_database import connect_database
from game import accounts, banking
from game.settlement import account_scope, read_state


class BankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'bank.db';accounts.prepare(self.path)
        with closing(connect_database(self.path)) as c,c:
            self.a=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('banktest','fixture','Bank test',1000)").lastrowid
        accounts.join(self.path,self.a,'Test town',1000)
        self.scope=account_scope(self.a);self.scope.__enter__();self.addCleanup(self.scope.__exit__,None,None,None)
        self.c=connect_database(self.path);self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.state=read_state(self.c);self.sid=self.state['settlement']['settlement_id']
        # Gameplay funds the reserve when Bank rules are enabled. These isolated
        # primitive tests need the same funded starting condition.
        from game.expansion import fund
        with self.c:fund(self.c,self.state,1000)

    def refresh(self):
        self.state=read_state(self.c)
        return self.state

    def test_loan_ledger_balances_and_repayment(self):
        lid=banking.borrow(self.c,self.state,100,1000)
        self.assertEqual(self.refresh()['resources']['credits'],600)
        self.assertEqual(banking.principal(self.c,self.sid),100)
        banking.repay(self.c,self.state,lid,40,1001)
        self.assertEqual(banking.principal(self.c,self.sid),60)
        self.assertEqual(self.c.execute("SELECT sum(amount) FROM credit_transactions WHERE transfer_ref LIKE 'loan:%'").fetchone()[0],0)
        banking.repay(self.c,self.refresh(),lid,60,1002)
        self.assertEqual(banking.debt(self.c,self.sid),0)

    def test_no_recursive_borrowing(self):
        before=banking.value(self.c,self.state)
        banking.borrow(self.c,self.state,100,1000)
        self.assertEqual(banking.value(self.c,self.refresh()),before)

    def test_reject_invalid_loan_and_over_cap(self):
        for amount in (0,-1,49,50.5,100000):
            with self.assertRaises(ValueError):banking.borrow(self.c,self.state,amount,1000)
        self.assertEqual(banking.loans(self.c,self.sid),[])

    def test_borrowed_funds_cannot_be_invested(self):
        banking.borrow(self.c,self.state,100,1000)
        with self.assertRaises(ValueError):banking.invest(self.c,self.refresh(),501,3,1000)
        banking.invest(self.c,self.state,500,3,1000)
        self.assertEqual(self.refresh()['resources']['credits'],100)

    def test_reserved_credits_cannot_be_repaid_or_invested(self):
        lid=banking.borrow(self.c,self.state,100,1000)
        self.refresh()['reserved']['credits']=590
        with self.assertRaises(ValueError):banking.repay(self.c,self.state,lid,11,1001)
        with self.assertRaises(ValueError):banking.invest(self.c,self.state,11,3,1001)

    def test_early_withdrawal_forfeits_interest(self):
        iid=banking.invest(self.c,self.state,400,3,1000)
        banking.accrue(self.c,self.refresh(),87400)
        self.assertEqual(banking.investments(self.c,self.sid)[0]['accrued_interest'],3)
        banking.withdraw(self.c,self.refresh(),iid,87400)
        self.assertEqual(self.refresh()['resources']['credits'],500)

    def test_maturity_pays_principal_and_interest_once(self):
        banking.invest(self.c,self.state,400,3,1000)
        banking.accrue(self.c,self.refresh(),260200)
        self.assertEqual(self.refresh()['resources']['credits'],509)
        banking.accrue(self.c,self.state,260200)
        self.assertEqual(self.refresh()['resources']['credits'],509)

    def test_split_accrual_matches_single_interval(self):
        banking.invest(self.c,self.state,101,3,1000)
        for now in (1100,2200,4000,18000,45000,87400):banking.accrue(self.c,self.refresh(),now)
        self.assertEqual(banking.investments(self.c,self.sid)[0]['accrued_interest'],0)
        banking.accrue(self.c,self.refresh(),260200)
        self.assertEqual(self.refresh()['resources']['credits'],502)

    def test_reject_foreign_financial_ids(self):
        with self.assertRaises(ValueError):banking.withdraw(self.c,self.state,999,1000)
        with self.assertRaises(ValueError):banking.repay(self.c,self.state,999,50,1000)

    def test_pause_shifts_maturity_and_interest(self):
        lid=banking.borrow(self.c,self.state,100,1000)
        iid=banking.invest(self.c,self.refresh(),100,3,1000)
        banking.shift_clock(self.c,self.refresh(),86400)
        self.assertEqual(banking.loans(self.c,self.sid)[0]['interest_processed_at'],87400)
        self.assertEqual(banking.investments(self.c,self.sid)[0]['matures_at'],346600)

    def test_interest_replay_is_idempotent_and_interest_paid_first(self):
        lid=banking.borrow(self.c,self.state,100,1000)
        banking.accrue(self.c,self.refresh(),86400)
        self.assertEqual(banking.debt(self.c,self.sid),102)
        banking.accrue(self.c,self.refresh(),86400)
        banking.repay(self.c,self.refresh(),lid,2,86400)
        self.assertEqual(banking.principal(self.c,self.sid),100)

    def test_bank_failure_disabled_even_if_reserves_negative(self):
        self.c.execute('UPDATE season_bank SET credits=-1000')
        lid=banking.borrow(self.c,self.state,100,1000)
        self.assertEqual(banking.loans(self.c,self.sid)[0]['daily_rate'],0.04)
