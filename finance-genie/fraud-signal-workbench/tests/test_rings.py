import unittest
from typing import cast

from neo4j import Driver
from graph_fraud_analyst.backend.services import rings


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _Session:
    def __init__(self, results):
        self._results = iter(results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, *_args, **_kwargs):
        return _Result(next(self._results))


class _Driver:
    def __init__(self, results):
        self._results = results

    def session(self):
        return _Session(self._results)


class RingServiceTests(unittest.TestCase):
    def test_list_rings_normalizes_risk_score_to_unit_interval(self):
        driver = _Driver(
            [
                [
                    {
                        "community_id": 1,
                        "member_count": 10,
                        "avg_risk_score": 2.8,
                        "anchor_merchant_categories": ["Fuel"],
                        "total_volume_usd": 1000,
                    },
                    {
                        "community_id": 2,
                        "member_count": 8,
                        "avg_risk_score": 1.4,
                        "anchor_merchant_categories": ["Retail"],
                        "total_volume_usd": 500,
                    },
                    {
                        "community_id": 3,
                        "member_count": 6,
                        "avg_risk_score": 0.7,
                        "anchor_merchant_categories": [],
                        "total_volume_usd": 250,
                    },
                ],
                [
                    {"cid": 1, "nodes": [], "edges": []},
                    {"cid": 2, "nodes": [], "edges": []},
                    {"cid": 3, "nodes": [], "edges": []},
                ],
            ]
        )

        result = rings.list_rings(cast(Driver, driver), max_nodes=500)

        self.assertEqual([ring.risk_score for ring in result], [1.0, 0.5, 0.25])
        self.assertEqual([ring.risk for ring in result], ["H", "M", "L"])

    def test_list_rings_handles_zero_max_risk_score(self):
        driver = _Driver(
            [
                [
                    {
                        "community_id": 1,
                        "member_count": 10,
                        "avg_risk_score": 0,
                        "anchor_merchant_categories": [],
                        "total_volume_usd": 0,
                    }
                ],
                [{"cid": 1, "nodes": [], "edges": []}],
            ]
        )

        result = rings.list_rings(cast(Driver, driver), max_nodes=500)

        self.assertEqual(result[0].risk_score, 0.0)
        self.assertEqual(result[0].risk, "L")


if __name__ == "__main__":
    unittest.main()
