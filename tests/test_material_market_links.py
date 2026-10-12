"""Shortfall navigation reflects spendable stock without changing game rules."""
import copy
import unittest
from game.building_views import material_market_link

class MaterialMarketLinkTests(unittest.TestCase):
    def test_each_shortfall_uses_unreserved_stock_and_links_to_market(self):
        state=dict(resources=dict(scrap=20,metal=2,electronics=0),reserved=dict(scrap=15))
        before=copy.deepcopy(state)
        html=material_market_link(state,dict(scrap=10,metal=5,electronics=2))
        self.assertIn('5 Scrap, 3 Metal, 2 Electronics',html)
        self.assertIn('href="#market"',html)
        self.assertEqual(state,before)

    def test_no_link_when_exact_cost_available(self):
        state=dict(resources=dict(scrap=10,metal=5,electronics=2))
        self.assertEqual(material_market_link(state,dict(scrap=10,metal=5,electronics=2)),'')
