"""Primary map purpose must not depend on secondary outputs or build status."""
import unittest
from game.building_views import map_purpose


class MapPurposeTests(unittest.TestCase):
    def test_food_with_secondary_oxygen_keeps_food_identity(self):
        self.assertEqual(map_purpose(dict(category='Food',oxygen_output=1)),('Food','#7fae74','F'))

    def test_storage_categories_have_consistent_distinct_purpose(self):
        for category in ('Food Storage','Water Storage','Material Storage'):
            self.assertEqual(map_purpose(dict(category=category)),('Storage','#9f8ab8','S'))

    def test_utilities_and_military_are_distinct_and_have_text_symbols(self):
        purposes=[map_purpose(dict(category=c)) for c in ('Water','Oxygen','Electricity','Drones')]
        self.assertEqual(len({p[1] for p in purposes}),4)
        self.assertTrue(all(p[2] for p in purposes))
        self.assertEqual(map_purpose(dict(category='Munitions')),map_purpose(dict(category='Defense')))

    def test_unknown_category_is_readable_support_fallback(self):
        self.assertEqual(map_purpose({}),('Support','#9ba8b4','+'))
