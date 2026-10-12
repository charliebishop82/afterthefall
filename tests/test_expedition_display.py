"""Active-trip visibility and clear crew identities without game-state writes."""
import unittest
from game.expeditions import display_rows,crew_label,summary,live

class ExpeditionDisplayTests(unittest.TestCase):
    def row(self,eid,status='returned'):
        return dict(expedition_id=eid,status=status,started_at=1000,gather_until=4600,returns_at=5500,
                    yields='{"scrap":2}',crew=[dict(id=7,name='Alex Ash',level=2)])
    def test_old_active_trip_not_hidden_by_many_completed_trips(self):
        state=dict(expeditions=[self.row(1,'exploring')]+[self.row(i) for i in range(2,25)])
        rows=display_rows(state)
        self.assertEqual(rows[0]['expedition_id'],1);self.assertEqual(len(rows),11)
    def test_crew_names_ids_and_launch_levels_are_explicit(self):
        self.assertEqual(crew_label(self.row(1)),'Alex Ash (#7, level 2 at launch)')
    def test_overview_has_management_link_and_escapes_names(self):
        row=self.row(1,'exploring');row['crew'][0]['name']='<script>'
        state=dict(expeditions=[row],settlement=dict(simulation_processed_at=2800))
        html=summary(state)
        self.assertIn('href="#expeditions"',html);self.assertIn('home in 45 min',html)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        result=live(state)[0];self.assertEqual(result['elapsed'],1800)
    def test_completed_elapsed_time_stops_at_arrival(self):
        state=dict(expeditions=[self.row(1)],settlement=dict(simulation_processed_at=10000))
        self.assertEqual(live(state)[0]['elapsed'],4500)
