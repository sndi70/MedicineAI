import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from app import (
    calculate_run_out_date,
    create_app,
    extract_package_size,
    normalize_package_size,
)


class MedicineCabinetTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "test.sqlite"
        self.app = create_app({"TESTING": True, "DATABASE": str(database_path)})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_member(self, name="Мария"):
        response = self.client.post("/api/family", json={"name": name})
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def test_family_member_name_cannot_be_duplicated(self):
        self.add_member("Мария")

        response = self.client.post("/api/family", json={"name": "Мария"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"],
            "Член на семейството с това име вече съществува.",
        )

        case_variant = self.client.post("/api/family", json={"name": "мАРИЯ"})
        self.assertEqual(case_variant.status_code, 409)
        self.assertEqual(len(self.client.get("/api/family").get_json()), 1)

    def valid_medicine(self, member_id):
        return {
            "memberId": member_id,
            "barcode": "3800000000000",
            "productName": "Витамини",
            "imageUrl": "https://example.com/product.jpg",
            "packageSize": "30 таблетки",
            "quantity": 2,
            "purchaseDate": "2026-10-28",
            "dailyUsage": "1 таблетка дневно",
        }

    def test_family_and_medicine_crud(self):
        member_id = self.add_member()
        response = self.client.post(
            "/api/medicines",
            json=self.valid_medicine(member_id),
        )
        self.assertEqual(response.status_code, 201)
        medicine_id = response.get_json()["id"]

        members = self.client.get("/api/family").get_json()
        self.assertEqual(members, [{"id": member_id, "name": "Мария", "medicine_count": 1}])
        medicines = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()
        self.assertEqual(medicines[0]["productName"], "Витамини")
        self.assertEqual(medicines[0]["memberId"], member_id)

        empty_member_id = self.add_member("Алекс")
        overview = self.client.get("/api/overview").get_json()
        self.assertEqual(overview["members"], members + [
            {"id": empty_member_id, "name": "Алекс", "medicine_count": 0}
        ])
        self.assertEqual(
            overview["medicines"],
            [
                {"memberId": member_id, "medicines": medicines},
                {"memberId": empty_member_id, "medicines": []},
            ],
        )

        self.assertEqual(
            self.client.delete("/api/medicines/{}".format(medicine_id)).status_code,
            204,
        )
        self.assertEqual(
            self.client.delete("/api/family/{}".format(member_id)).status_code,
            204,
        )

    def test_deleting_family_member_also_deletes_their_medicines(self):
        member_id = self.add_member()
        self.client.post(
            "/api/medicines",
            json=self.valid_medicine(member_id),
        )

        self.assertEqual(
            self.client.delete("/api/family/{}".format(member_id)).status_code,
            204,
        )
        self.assertEqual(self.client.get("/api/family").get_json(), [])
        self.assertEqual(self.client.get("/api/overview").get_json()["medicines"], [])
        self.assertEqual(
            self.client.get("/api/medicines?memberId={}".format(member_id)).status_code,
            404,
        )

    def test_missing_medicine_image_can_be_saved_and_is_returned(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["imageUrl"] = None
        medicine_id = self.client.post("/api/medicines", json=medicine).get_json()["id"]

        response = self.client.patch(
            "/api/medicines/{}/image".format(medicine_id),
            json={"imageUrl": "https://images.example.com/medicine.jpg"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["imageUrl"],
            "https://images.example.com/medicine.jpg",
        )
        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(
            listed_medicine["imageUrl"],
            "https://images.example.com/medicine.jpg",
        )

    def test_medicine_image_update_rejects_non_https_and_missing_medicine(self):
        response = self.client.patch(
            "/api/medicines/1/image",
            json={"imageUrl": "http://images.example.com/medicine.jpg"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.patch(
            "/api/medicines/1/image",
            json={"imageUrl": "https://images.example.com/medicine.jpg"},
        )
        self.assertEqual(response.status_code, 404)

    def test_medicine_image_update_does_not_replace_existing_image(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine_id = self.client.post("/api/medicines", json=medicine).get_json()["id"]

        response = self.client.patch(
            "/api/medicines/{}/image".format(medicine_id),
            json={"imageUrl": "https://images.example.com/other-medicine.jpg"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["imageUrl"], medicine["imageUrl"])

    def test_invalid_medicine_data_is_rejected(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["barcode"] = "123456789"
        response = self.client.post("/api/medicines", json=medicine)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Баркодът", response.get_json()["error"])

        medicine = self.valid_medicine(member_id)
        medicine["quantity"] = True
        self.assertEqual(
            self.client.post("/api/medicines", json=medicine).status_code,
            400,
        )

    def test_medicine_run_out_date_uses_quantity_package_size_usage_and_purchase_date(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["quantity"] = 2
        response = self.client.post("/api/medicines", json=medicine)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["runOutDate"], "2026-12-27")

        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(listed_medicine["runOutDate"], "2026-12-27")

    def test_medicine_run_out_date_accounts_for_daily_frequency(self):
        medicine = {
            "quantity": 1,
            "packageSize": "30 таблетки",
            "dailyUsage": "1 таблетка 2 пъти дневно",
            "purchaseDate": "2026-10-28",
        }
        self.assertEqual(calculate_run_out_date(medicine), "2026-11-12")

    def test_medicine_run_out_date_uses_bare_numeric_package_and_daily_usage(self):
        medicine = {
            "quantity": 1,
            "packageSize": "25",
            "dailyUsage": "1",
            "purchaseDate": "2026-10-01",
        }
        self.assertEqual(calculate_run_out_date(medicine), "2026-10-26")

    def test_medicine_run_out_date_uses_package_count_from_product_name_when_package_size_missing(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["productName"] = "НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР."
        medicine["packageSize"] = None
        medicine["dailyUsage"] = "1"
        medicine["quantity"] = 1
        medicine["purchaseDate"] = "2026-10-02"
        medicine_id = self.client.post("/api/medicines", json=medicine).get_json()["id"]

        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(listed_medicine["id"], medicine_id)
        self.assertEqual(listed_medicine["runOutDate"], "2026-10-30")

    def test_extract_package_size_from_common_product_name_formats(self):
        examples = (
            ("НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР.", "28 таблетки"),
            ("РОЗВЕРА 20 МГ ТАБЛ. Х 30", "30 таблетки"),
            ("Лекарство 20 капсули", "20 капсули"),
            ("Product 100 ml", "100 мл"),
            ("Продукт 20 г", "20 г"),
            ("Витамин 500 mg", ""),
        )
        for product_name, expected in examples:
            with self.subTest(product_name=product_name):
                self.assertEqual(extract_package_size(product_name), expected)

    def test_tablet_package_size_converts_catalog_piece_count(self):
        self.assertEqual(
            normalize_package_size("28 бр.", "НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР."),
            "28 таблетки",
        )
        self.assertEqual(
            normalize_package_size("28 tablets", "Medicine tablets x 28"),
            "28 таблетки",
        )
        self.assertEqual(
            normalize_package_size("28 бр.", "Лекарство 28 капсули"),
            "28 бр.",
        )

    def test_medicine_run_out_date_is_omitted_when_units_cannot_be_matched(self):
        medicine = {
            "quantity": 1,
            "packageSize": "30 таблетки",
            "dailyUsage": "5 мл дневно",
            "purchaseDate": "2026-10-28",
        }
        self.assertIsNone(calculate_run_out_date(medicine))

    def test_medicine_run_out_date_is_omitted_for_zero_daily_frequency(self):
        medicine = {
            "quantity": 1,
            "packageSize": "30 таблетки",
            "dailyUsage": "1 таблетка 0 пъти дневно",
            "purchaseDate": "2026-10-28",
        }
        self.assertIsNone(calculate_run_out_date(medicine))

    def test_existing_medicine_uses_verified_product_image_when_missing(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["barcode"] = "3838989598839"
        medicine["productName"] = "РОЗВЕРА 20 МГ ТАБЛ. Х 30"
        medicine["imageUrl"] = None
        medicine["packageSize"] = "30 таблетки"
        self.assertEqual(
            self.client.post("/api/medicines", json=medicine).status_code,
            201,
        )

        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(
            listed_medicine["imageUrl"],
            "https://static.framar.bg/product/160614135936rozvera.jpg",
        )

    def test_existing_piracetam_medicine_uses_verified_product_image(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["barcode"] = "4024773001732"
        medicine["productName"] = "ПИРАЦЕТАМ АЛ ТАБЛ. 800МГ. Х 60БР."
        medicine["imageUrl"] = None
        medicine["packageSize"] = None
        self.assertEqual(
            self.client.post("/api/medicines", json=medicine).status_code,
            201,
        )

        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(
            listed_medicine["imageUrl"],
            "https://static.framar.bg/product/240903102002piracetam-al.jpg",
        )

    def test_existing_nebilet_medicine_uses_verified_product_image(self):
        member_id = self.add_member()
        medicine = self.valid_medicine(member_id)
        medicine["barcode"] = "4013054002162"
        medicine["productName"] = "НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР."
        medicine["imageUrl"] = None
        medicine["packageSize"] = None
        self.assertEqual(
            self.client.post("/api/medicines", json=medicine).status_code,
            201,
        )

        listed_medicine = self.client.get(
            "/api/medicines?memberId={}".format(member_id)
        ).get_json()[0]
        self.assertEqual(
            listed_medicine["imageUrl"],
            "https://static.ayanmarket.kz/products/images/dafas/4013054002162.png",
        )

    def test_invalid_json_and_missing_member_return_json_errors(self):
        response = self.client.post(
            "/api/family",
            data="{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())
        self.assertEqual(
            self.client.get("/api/medicines?memberId=999").status_code,
            404,
        )

    @patch("app.urlopen")
    def test_product_lookup_returns_product_details(self, mocked_urlopen):
        response_mock = mocked_urlopen.return_value.__enter__.return_value
        response_mock.read.return_value = json.dumps(
            {
                "status": 1,
                "product": {
                    "product_name": "Витамини",
                    "image_front_url": "https://example.com/product.jpg",
                    "quantity": "30 таблетки",
                },
            }
        ).encode("utf-8")

        response = self.client.get("/api/lookup/3800000000000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "found": True,
                "productName": "Витамини",
                "imageUrl": "https://example.com/product.jpg",
                "packageSize": "30 таблетки",
                "source": "Open Food Facts",
            },
        )
        self.assertEqual(mocked_urlopen.call_count, 5)
        requested_urls = {
            call.args[0].full_url
            for call in mocked_urlopen.call_args_list
        }
        self.assertTrue(any("barcode.bg" in url for url in requested_urls))
        self.assertTrue(any("world.openfoodfacts.org" in url for url in requested_urls))
        self.assertTrue(any("world.openproductsfacts.org" in url for url in requested_urls))
        self.assertTrue(any("world.openbeautyfacts.org" in url for url in requested_urls))
        self.assertTrue(any("world.openpetfoodfacts.org" in url for url in requested_urls))

    @patch("app.urlopen", side_effect=HTTPError("https://example.com", 404, "Not Found", {}, None))
    def test_product_lookup_reports_unknown_barcode_as_not_found(self, _mocked_urlopen):
        response = self.client.get("/api/lookup/3800000000000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["found"], False)
        self.assertEqual(len(response.get_json()["sourcesSearched"]), 5)

    @patch("app.urlopen")
    def test_product_lookup_finds_barcode_bg_product(self, mocked_urlopen):
        barcode_bg_html = """
            <table class="randomBarcodes">
                <tr><th>Баркод</th><th>Име на продукта</th></tr>
                <tr>
                    <td>1</td>
                    <td>3838989598839</td>
                    <td>РОЗВЕРА 20 МГ ТАБЛ. Х 30</td>
                    <td>ОП.</td>
                </tr>
            </table>
        """.encode("utf-8")

        def respond(lookup_request, timeout, context):
            if "barcode.bg" in lookup_request.full_url:
                response = MagicMock()
                response.__enter__.return_value.read.return_value = barcode_bg_html
                return response
            raise HTTPError(lookup_request.full_url, 404, "Not Found", {}, None)

        mocked_urlopen.side_effect = respond

        response = self.client.get("/api/lookup/3838989598839")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "found": True,
                "productName": "РОЗВЕРА 20 МГ ТАБЛ. Х 30",
                "imageUrl": "https://static.framar.bg/product/160614135936rozvera.jpg",
                "packageSize": "30 таблетки",
                "source": "Barcode.bg",
            },
        )

    @patch("app.urlopen")
    def test_product_lookup_extracts_nebilet_package_size_from_barcode_bg_name(self, mocked_urlopen):
        barcode_bg_html = """
            <table class="randomBarcodes">
                <tr>
                    <td>1</td>
                    <td>4013054002162</td>
                    <td>НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР.</td>
                    <td>ОПАКОВКА</td>
                </tr>
            </table>
        """.encode("utf-8")

        def respond(lookup_request, timeout, context):
            response = MagicMock()
            if "barcode.bg" in lookup_request.full_url:
                body = barcode_bg_html
            else:
                raise HTTPError(lookup_request.full_url, 404, "Not Found", {}, None)
            response.__enter__.return_value.read.return_value = body
            return response

        mocked_urlopen.side_effect = respond

        response = self.client.get("/api/lookup/4013054002162")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["packageSize"], "28 таблетки")

    @patch("app.urlopen")
    def test_product_lookup_normalizes_catalog_piece_count_for_tablets(self, mocked_urlopen):
        response_mock = mocked_urlopen.return_value.__enter__.return_value
        response_mock.read.return_value = json.dumps(
            {
                "status": 1,
                "product": {
                    "product_name": "НЕБИЛЕТ ТАБЛ. 5МГ / 28 БР.",
                    "quantity": "28 бр.",
                },
            }
        ).encode("utf-8")

        response = self.client.get("/api/lookup/4013054002162")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["packageSize"], "28 таблетки")

    @patch("app.urlopen")
    def test_barcode_bg_result_uses_image_from_another_barcode_catalog(self, mocked_urlopen):
        barcode_bg_html = """
            <table class="randomBarcodes">
                <tr>
                    <td>1</td>
                    <td>5901234123457</td>
                    <td>Тестово лекарство таблетки х 30</td>
                    <td>ОП.</td>
                </tr>
            </table>
        """.encode("utf-8")

        def respond(lookup_request, timeout, context):
            response = MagicMock()
            if "barcode.bg" in lookup_request.full_url:
                body = barcode_bg_html
            elif "world.openproductsfacts.org" in lookup_request.full_url:
                body = json.dumps(
                    {
                        "status": 1,
                        "product": {
                            "product_name": "Test medicine",
                            "image_front_url": "https://example.com/medicine.jpg",
                            "quantity": "30 tablets",
                        },
                    }
                ).encode("utf-8")
            else:
                raise HTTPError(lookup_request.full_url, 404, "Not Found", {}, None)
            response.__enter__.return_value.read.return_value = body
            return response

        mocked_urlopen.side_effect = respond

        response = self.client.get("/api/lookup/5901234123457")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source"], "Barcode.bg")
        self.assertEqual(
            response.get_json()["imageUrl"],
            "https://example.com/medicine.jpg",
        )

    @patch("app.urlopen")
    def test_product_lookup_falls_back_to_another_public_catalog(self, mocked_urlopen):
        def respond(request, timeout, context):
            if "world.openfoodfacts.org" in request.full_url:
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            if "world.openproductsfacts.org" not in request.full_url:
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                {
                    "status": 1,
                    "product": {
                        "product_name": "Намерен продукт",
                        "image_front_url": "https://example.com/product.jpg",
                        "quantity": "20 таблетки",
                    },
                }
            ).encode("utf-8")
            return response

        mocked_urlopen.side_effect = respond
        response = self.client.get("/api/lookup/3800000000000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["productName"], "Намерен продукт")
        self.assertEqual(response.get_json()["source"], "Open Products Facts")
        self.assertEqual(mocked_urlopen.call_count, 5)

    @patch("app.urlopen", side_effect=URLError("catalog unavailable"))
    def test_product_lookup_reports_when_all_catalogs_are_unavailable(self, _mocked_urlopen):
        response = self.client.get("/api/lookup/3800000000000")
        self.assertEqual(response.status_code, 502)
        self.assertIn("публичните продуктови каталози", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
