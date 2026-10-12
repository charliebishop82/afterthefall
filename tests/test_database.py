"""Behavioral checks for V1 persistence; no third-party test dependencies."""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from database import create_database as db


EXPECTED_TABLES = set("""
accounts seasons settlements citizens citizen_settlement_history
citizen_assignments citizen_xp_events citizen_level_history citizen_morale_events
season_derelicts settlement_derelicts buildings settlement_jobs building_state_events
settlement_resources resource_reservations settlement_policies military_units
military_inventory attacks attack_citizens attack_drones attack_munitions battle_reports
vault_allocations season_bank bank_loans bank_investments credit_transactions
market_listings market_transactions trade_proposals trade_items treaties
private_messages board_posts news_events notifications game_events admin_actions
""".split())

FIXTURE = """
INSERT INTO accounts VALUES (1, 'alice', 'not-a-real-hash', 'Alice', 0, 1, 0);
INSERT INTO accounts VALUES (2, 'bob', 'not-a-real-hash', 'Bob', 0, 1, 0);
INSERT INTO seasons (season_id,name,status,scheduled_start_at,finalization_at,ends_at,created_at,config_version)
VALUES (1,'One','active',0,9000,10000,0,'test-only'), (2,'Two','active',0,9000,10000,0,'test-only');
INSERT INTO settlements (settlement_id,season_id,account_id,settlement_name,town_hall_x,town_hall_y,
                        created_at,status,simulation_processed_at)
VALUES (1,1,1,'Avalon',20,20,0,'active',0), (2,1,2,'Rust',20,20,0,'active',0),
       (3,2,1,'Avalon',20,20,0,'active',0);
INSERT INTO citizens (citizen_id,settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at)
VALUES (1,1,1,'A Citizen','female',100,60,'alive',0), (2,1,1,'B Citizen','male',100,60,'alive',0);
INSERT INTO buildings (building_id,settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at)
VALUES (1,1,'town_hall',1,20,20,1000,'active',0), (2,2,'town_hall',1,20,20,1000,'active',0),
       (3,1,'drone_factory',1,10,10,900,'active',0), (4,1,'offensive_hangar',1,5,5,600,'active',0);
INSERT INTO settlement_resources (settlement_id,food,credits,updated_at) VALUES (1,10.5,100,0);
INSERT INTO season_bank VALUES (1,1000,0);
INSERT INTO military_units VALUES (1,1,'offensive_drone',100,4,'available',0,NULL);
INSERT INTO military_inventory VALUES (1,1,4,'missile',2,0);
INSERT INTO attacks (attack_id,season_id,attacker_settlement_id,defender_settlement_id,
                     launched_at,resolves_at,status,raid_objective,random_seed)
VALUES (1,1,1,2,0,100,'in_flight','balanced','test-seed'),
       (2,1,1,2,0,100,'in_flight','balanced','another-test-seed');
"""


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'game.db'
        db.create_database(self.path)
        self.connection = db.connect_database(self.path)
        self.addCleanup(self.connection.close)

    def seed(self):
        self.connection.executescript(FIXTURE)

    def rejects(self, sql, parameters=()):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(sql, parameters)

    def test_fresh_schema_is_empty_complete_and_valid(self):
        actual = {r[0] for r in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(actual, EXPECTED_TABLES)
        for table in actual:
            self.assertEqual(self.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(self.connection.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(self.connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_every_connection_enforces_foreign_keys(self):
        with closing(db.connect_database(self.path)) as another:
            self.assertEqual(another.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                another.execute('INSERT INTO settlement_resources (settlement_id,updated_at) VALUES (999,0)')

    def test_connection_does_not_create_missing_database(self):
        missing = self.path.with_name('missing.db')
        with self.assertRaises(sqlite3.OperationalError):
            db.connect_database(missing)
        self.assertFalse(missing.exists())

    def test_existing_database_is_unchanged(self):
        self.seed()
        before = hashlib.sha256(self.path.read_bytes()).digest()
        with self.assertRaises(FileExistsError):
            db.create_database(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)

    def test_existing_empty_file_is_preserved(self):
        empty = self.path.with_name('empty.db')
        empty.touch()
        with self.assertRaises(FileExistsError):
            db.create_database(empty)
        self.assertEqual(empty.read_bytes(), b'')

    def test_failed_creation_removes_only_new_file(self):
        failed = self.path.with_name('failed.db')
        with patch.object(db, 'SCHEMA_SQL', 'CREATE TABLE partial(id INTEGER); INVALID SQL;'):
            with self.assertRaises(sqlite3.Error):
                db.create_database(failed)
        self.assertFalse(failed.exists())
        self.assertTrue(self.path.exists())
        db.create_database(failed)

    def test_cli_from_another_directory_and_repeat_refusal(self):
        script = Path(db.__file__).resolve()
        output = self.path.parent / 'nested' / 'cli.db'
        command = [sys.executable, str(script), '--path', str(output)]
        result = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Created empty V1 database', result.stdout)
        result = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Refusing to overwrite', result.stderr)

    def test_names_and_one_settlement_per_season(self):
        self.seed()
        self.rejects("UPDATE accounts SET username='alice' WHERE account_id=2")
        self.rejects("UPDATE accounts SET display_name='Alice' WHERE account_id=2")
        self.rejects('UPDATE settlements SET account_id=1 WHERE settlement_id=2')
        self.rejects("UPDATE settlements SET settlement_name='Avalon' WHERE settlement_id=2")
        # The fixture reuses account 1 and the name Avalon in a different season.
        self.assertEqual(self.connection.execute('SELECT count(*) FROM settlements').fetchone()[0], 3)

    def test_citizen_ranges_and_numeric_storage(self):
        self.seed()
        for column, value in [('level',0), ('level',11), ('level',1.5), ('morale',-1),
                              ('morale',101), ('current_hp',-1), ('xp',-0.1)]:
            with self.subTest(column=column,value=value):
                self.rejects(f'UPDATE citizens SET {column}=? WHERE citizen_id=1', (value,))
        self.connection.execute('UPDATE citizens SET level=10,morale=100,xp=1.5,current_hp=0 WHERE citizen_id=1')

    def test_resources_credits_and_negative_bank(self):
        self.seed()
        for column in ['food','water','scrap','metal','electronics','credits']:
            self.rejects(f'UPDATE settlement_resources SET {column}=-1 WHERE settlement_id=1')
        self.rejects('UPDATE settlement_resources SET credits=1.5 WHERE settlement_id=1')
        self.rejects("UPDATE settlement_resources SET food='not a quantity' WHERE settlement_id=1")
        self.connection.execute('UPDATE settlement_resources SET food=0.125 WHERE settlement_id=1')
        self.connection.execute('UPDATE season_bank SET credits=-500 WHERE season_id=1')
        self.assertEqual(self.connection.execute('SELECT credits FROM season_bank').fetchone()[0], -500)

    def test_map_coordinates_rotation_and_hp(self):
        self.seed()
        for column, value in [('origin_x',-1), ('origin_y',40), ('rotation',45), ('current_hp',-1)]:
            self.rejects(f'UPDATE buildings SET {column}=? WHERE building_id=1', (value,))
        self.rejects('UPDATE settlements SET town_hall_x=40 WHERE settlement_id=1')
        self.connection.execute('UPDATE buildings SET origin_x=39,rotation=90 WHERE building_id=1')

    def test_assignments_end_and_history_survives_capture(self):
        self.seed()
        self.connection.execute("INSERT INTO citizen_assignments (citizen_id,settlement_id,assignment_type,assigned_at) VALUES (1,1,'patrol',0)")
        self.rejects("INSERT INTO citizen_assignments (citizen_id,settlement_id,assignment_type,assigned_at) VALUES (1,1,'guard',1)")
        self.connection.execute("UPDATE citizen_assignments SET ended_at=1,end_reason='captured'")
        self.connection.execute("INSERT INTO citizen_settlement_history (citizen_id,settlement_id,joined_at,arrival_reason) VALUES (1,1,0,'start')")
        self.rejects("INSERT INTO citizen_settlement_history (citizen_id,settlement_id,joined_at,arrival_reason) VALUES (1,2,1,'capture')")
        self.connection.execute("UPDATE citizen_settlement_history SET left_at=1,departure_reason='capture'")
        self.connection.execute('UPDATE citizens SET settlement_id=2,integrated=0 WHERE citizen_id=1')
        self.connection.execute("INSERT INTO citizen_settlement_history (citizen_id,settlement_id,previous_settlement_id,joined_at,arrival_reason,related_attack_id) VALUES (1,2,1,1,'capture',1)")
        self.connection.execute("INSERT INTO citizen_assignments (citizen_id,settlement_id,assignment_type,assigned_at) VALUES (1,2,'patrol',2)")
        self.assertEqual(self.connection.execute('SELECT original_settlement_id FROM citizens WHERE citizen_id=1').fetchone()[0], 1)
        self.rejects('DELETE FROM citizens WHERE citizen_id=1')
        self.assertEqual(self.connection.execute('SELECT count(*) FROM citizen_settlement_history').fetchone()[0], 2)

    def test_no_self_or_cross_season_attack(self):
        self.seed()
        self.rejects('UPDATE attacks SET defender_settlement_id=1 WHERE attack_id=1')
        self.rejects('UPDATE attacks SET defender_settlement_id=3 WHERE attack_id=1')
        self.rejects('UPDATE attacks SET season_id=2 WHERE attack_id=1')
        self.assertEqual([r[0] for r in self.connection.execute(
            "SELECT attack_id FROM attacks WHERE status='in_flight' ORDER BY resolves_at,attack_id")], [1,2])

    def test_citizens_and_drones_cannot_be_committed_twice(self):
        self.seed()
        for table, column in [('attack_citizens','citizen_id'), ('attack_drones','unit_id')]:
            sql = f'INSERT INTO {table} (attack_id,{column},participant_settlement_id,role,committed_at) VALUES (?,1,1,\'attacker\',0)'
            self.connection.execute(sql, (1,))
            self.rejects(sql, (2,))
            self.connection.execute(f'UPDATE {table} SET released_at=100 WHERE attack_id=1')
            self.connection.execute(sql, (2,))

    def test_hardware_storage_ownership(self):
        self.seed()
        self.rejects('UPDATE military_units SET home_building_id=2 WHERE unit_id=1')
        self.rejects('UPDATE military_inventory SET building_id=2 WHERE inventory_id=1')
        self.rejects('UPDATE military_inventory SET quantity=0.5 WHERE inventory_id=1')
        self.rejects('DELETE FROM buildings WHERE building_id=4')

    def test_jobs_target_progress_and_manufacturing_queue(self):
        self.seed()
        sql = """INSERT INTO settlement_jobs (settlement_id,job_type,target_type,target_building_id,
                 production_building_id,output_type,output_quantity,work_required,status,created_at,last_processed_at)
                 VALUES (1,'manufacturing','building',3,3,'offensive_drone',1,10,?,0,0)"""
        self.connection.execute(sql, ('active',))
        self.rejects(sql, ('paused',))
        self.connection.execute(sql, ('queued',))
        self.rejects('UPDATE settlement_jobs SET work_completed=11 WHERE job_id=1')
        self.rejects('UPDATE settlement_jobs SET target_building_id=NULL WHERE job_id=1')
        self.rejects('UPDATE settlement_jobs SET target_building_id=2 WHERE job_id=1')
        self.rejects('UPDATE settlement_jobs SET target_unit_id=1 WHERE job_id=1')
        self.connection.execute("UPDATE settlement_jobs SET status='completed',work_completed=10 WHERE job_id=1")
        self.connection.execute("UPDATE settlement_jobs SET status='active' WHERE job_id=2")

    def test_derelicts_are_private_and_season_scoped(self):
        self.seed()
        self.connection.execute("INSERT INTO season_derelicts VALUES (1,1,'ruined_house',3,3,0)")
        sql = """INSERT INTO settlement_derelicts (settlement_id,season_id,season_derelict_id,
                 status,random_key_ref,random_nonce,created_at) VALUES (?,1,1,'untouched','key-v1',?,0)"""
        self.connection.execute(sql, (1,'private-1'))
        self.connection.execute(sql, (2,'private-2'))
        self.rejects(sql, (1,'duplicate'))
        self.rejects(sql, (3,'wrong-season'))
        self.rejects("UPDATE settlement_derelicts SET random_result='broken json'")

    def test_treaty_types_coexist_and_history_is_retained(self):
        self.seed()
        sql = """INSERT INTO treaties (season_id,settlement_a_id,settlement_b_id,treaty_type,
                 status,proposer_settlement_id,proposed_at) VALUES (1,1,2,?,'active',1,0)"""
        self.connection.execute(sql, ('peace',))
        self.connection.execute(sql, ('trade_agreement',))
        self.rejects(sql, ('peace',))
        self.rejects('UPDATE treaties SET settlement_b_id=3 WHERE treaty_id=1')
        self.rejects('UPDATE treaties SET settlement_a_id=2,settlement_b_id=1 WHERE treaty_id=1')
        self.connection.execute("UPDATE treaties SET status='cancelled',cancelled_at=1 WHERE treaty_id=1")
        self.connection.execute(sql, ('peace',))

    def test_trade_reservations_and_market_constraints(self):
        self.seed()
        self.connection.execute("INSERT INTO trade_proposals VALUES (1,1,1,2,'pending',0,100,NULL)")
        self.rejects('UPDATE trade_proposals SET recipient_settlement_id=3 WHERE trade_id=1')
        self.connection.execute("INSERT INTO trade_items (trade_id,side,resource_type,quantity) VALUES (1,'proposer','food',1.25)")
        self.rejects("INSERT INTO trade_items (trade_id,side,resource_type,quantity) VALUES (1,'recipient','credits',1.25)")
        self.connection.execute("INSERT INTO market_listings VALUES (1,1,1,'food',10,10,2,'open',0,NULL)")
        self.rejects('UPDATE market_listings SET remaining_quantity=11 WHERE listing_id=1')
        self.rejects("INSERT INTO resource_reservations (settlement_id,resource_type,quantity,created_at) VALUES (1,'food',1,0)")
        self.rejects("INSERT INTO resource_reservations (settlement_id,resource_type,quantity,market_listing_id,trade_proposal_id,created_at) VALUES (1,'food',1,1,1,0)")
        self.connection.execute("INSERT INTO resource_reservations (settlement_id,resource_type,quantity,market_listing_id,created_at) VALUES (1,'food',10,1,0)")
        self.assertEqual(self.connection.execute('SELECT food FROM settlement_resources').fetchone()[0],10.5)

    def test_multi_table_failure_rolls_back_whole_transaction(self):
        self.seed()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute('UPDATE settlement_resources SET credits=50 WHERE settlement_id=1')
                self.connection.execute('UPDATE season_bank SET credits=1050 WHERE season_id=1')
                self.connection.execute('UPDATE military_inventory SET quantity=-1 WHERE inventory_id=1')
        self.assertEqual(self.connection.execute('SELECT credits FROM settlement_resources').fetchone()[0],100)
        self.assertEqual(self.connection.execute('SELECT credits FROM season_bank').fetchone()[0],1000)


if __name__ == '__main__':
    unittest.main()
