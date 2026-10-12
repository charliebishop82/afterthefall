"""Market decisions respect own stock, prices, capacity and daily limits."""
import copy
import unittest
from unittest.mock import patch
from game.bot_market import choose_market


def decision(route,reason,**form):
    return dict(route=route,reason=reason,form=form)


class BotMarketTests(unittest.TestCase):
    def setUp(self):
        self.state=dict(season=dict(config_version='prototype_v1'),
            resources=dict(food=50,water=50,scrap=100,metal=40,electronics=10,credits=500),
            reserved={},jobs=[])
        self.market=dict(can_trade=True,resources={r:dict(stock=0,buy_price=p,sell_price=s,
            reserve_remaining=q,reserve_price=p) for r,p,s,q in
            [('food',2,1,30),('water',2,1,30),('scrap',3,2,20),('metal',6,4,10),('electronics',15,10,5)]})
        p=patch('game.economy.storage',return_value=dict(food=100,water=100,material=250))
        p.start();self.addCleanup(p.stop)

    def choose(self,rates=None,**kwargs):
        return choose_market(self.state,rates or {},1,decision,self.market,**kwargs)

    def test_urgent_food_uses_personal_reserve_when_shared_stock_empty(self):
        self.state['resources']['food']=0
        result=self.choose({'food':dict(net=-5,consumption=5)})
        self.assertEqual(result['form'],dict(action='reserve_buy',resource='food',quantity=30))
        self.assertIn('daily personal reserve',result['reason'])

    def test_shared_stock_preferred_on_equal_prices_and_cheaper_source_wins(self):
        self.market['resources']['metal']['stock']=10
        costs=dict(scrap=0,metal=43,electronics=0)
        result=self.choose(costs=costs)
        self.assertEqual(result['form']['action'],'buy')
        self.market['resources']['metal']['reserve_price']=5
        self.assertEqual(self.choose(costs=costs)['form']['action'],'reserve_buy')

    def test_nonurgent_purchase_retains_credit_buffer_and_fits_storage(self):
        self.state['resources']['credits']=56
        result=self.choose(costs=dict(scrap=100,metal=43,electronics=10))
        self.assertEqual(result['form']['quantity'],1)
        self.state['resources']['scrap']=200
        self.assertIsNone(self.choose(costs=dict(scrap=200,metal=43,electronics=10)))

    def test_zero_stock_and_used_daily_allowance_wait(self):
        self.market['resources']['electronics']['reserve_remaining']=0
        self.assertIsNone(self.choose(costs=dict(scrap=100,metal=40,electronics=15)))

    def test_surplus_sale_keeps_material_buffer_and_is_read_only(self):
        self.state['resources'].update(scrap=230,metal=0,electronics=0)
        before=copy.deepcopy((self.state,self.market))
        result=self.choose({'scrap':dict(net=5,consumption=0)})
        self.assertEqual(result['form'],dict(action='sell',resource='scrap',quantity=25))
        self.assertEqual((self.state,self.market),before)

    def test_reserved_stock_and_active_manufacturing_are_not_sold(self):
        self.state['resources'].update(scrap=230,metal=0,electronics=0)
        rates={'scrap':dict(net=5,consumption=0)}
        self.state['reserved']['scrap']=225
        self.assertIsNone(self.choose(rates))
        self.state['reserved']={}
        self.state['jobs']=[dict(job_type='manufacturing',status='paused')]
        self.assertIsNone(self.choose(rates))

    def test_deficit_resources_are_not_sold_and_paused_market_never_acts(self):
        self.state['resources'].update(food=95)
        self.assertIsNone(self.choose({'food':dict(net=-1,consumption=2)}))
        self.market['can_trade']=False
        self.state['resources']['food']=0
        self.assertIsNone(self.choose({'food':dict(net=-5,consumption=5)}))

    def test_reserved_credits_and_full_storage_block_purchases(self):
        self.state['reserved']['credits']=500
        self.assertIsNone(self.choose(costs=dict(scrap=110,metal=40,electronics=10)))
        self.state['reserved']={}
        self.state['resources']['scrap']=200
        self.assertIsNone(self.choose(costs=dict(scrap=200,metal=41,electronics=10)))

    def test_food_surplus_sales_preserve_six_hour_supply_buffer(self):
        self.state['resources']['food']=95
        result=self.choose({'food':dict(net=3,consumption=10)})
        self.assertEqual(result['form'],dict(action='sell',resource='food',quantity=25))

    def test_missing_market_snapshot_preserves_old_policy_compatibility(self):
        self.assertIsNone(choose_market(self.state,{},1,decision,None))
