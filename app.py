import json
import logging
import os
import re
import sqlite3
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from flask import Flask, current_app, g, jsonify, request, send_from_directory
import truststore
from werkzeug.exceptions import BadRequest, HTTPException, UnsupportedMediaType


BASE_DIR = Path(__file__).resolve().parent
BARCODE_PATTERN = re.compile(r"^(?:\d{8}|\d{12,14})$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRODUCT_CATALOGS = (
    ("Open Food Facts", "world.openfoodfacts.org"),
    ("Open Products Facts", "world.openproductsfacts.org"),
    ("Open Beauty Facts", "world.openbeautyfacts.org"),
    ("Open Pet Food Facts", "world.openpetfoodfacts.org"),
)
BARCODE_BG_SOURCE = "Barcode.bg"
BARCODE_BG_SEARCH_URL = "https://barcode.bg{}".format(
    quote("/barcode/BG/Информация-за-баркод.htm", safe="/")
)
PRODUCT_IMAGE_OVERRIDES = {
    "3838989598839": "https://static.framar.bg/product/160614135936rozvera.jpg",
    "4024773001732": "https://static.framar.bg/product/240903102002piracetam-al.jpg",
    "4013054002162": "https://static.ayanmarket.kz/products/images/dafas/4013054002162.png",
}
MEDICINE_UNIT_PATTERNS = (
    ("tablet", r"таблетк\w*|tablets?|tabs?"),
    ("capsule", r"капсул\w*|capsules?|caps?"),
    ("milliliter", r"мл|милилитр\w*|ml|millilit(?:er|re)s?"),
    ("drop", r"капк\w*|drops?"),
    ("piece", r"бр\.?|брой\w*|pieces?|pcs"),
    ("sachet", r"саше\w*|sachets?"),
    ("dose", r"доз\w*|doses?"),
)
PACKAGE_SIZE_PATTERNS = (
    ("таблетки", r"таблет(?:ка|ки|ок)\w*|табл\.?|tablets?|tabs?"),
    ("капсули", r"капсул(?:а|и)\w*|капс\.?|capsules?|caps?"),
    ("бр.", r"бр\.?|броя?\w*|pieces?|pcs"),
    ("мл", r"милилитр\w*|мл|millilit(?:er|re)s?|ml"),
    ("капки", r"капк\w*|drops?"),
    ("сашета", r"саше\w*|sachets?"),
    ("дози", r"доз\w*|doses?"),
    ("г", r"г(?:рам\w*)?|гр\.?|grams?|g"),
)


class BarcodeBgResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_results_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table" and "randomBarcodes" in attributes.get("class", "").split():
            self.in_results_table = True
        elif self.in_results_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_cell:
            self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append(self.current_row)
            self.in_row = False
        elif tag == "table" and self.in_results_table:
            self.in_results_table = False


def api_error(message, status):
    return jsonify({"error": message}), status


def parse_positive_integer(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if str(parsed) != str(value).strip() or parsed < 1:
        return None
    return parsed


def valid_date(value):
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def parse_medicine_amount(value):
    if not isinstance(value, str):
        return None
    numeric_value = value.strip().replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?", numeric_value):
        try:
            amount = Decimal(numeric_value)
        except InvalidOperation:
            return None
        return (amount, None) if amount > 0 else None

    for unit, pattern in MEDICINE_UNIT_PATTERNS:
        match = re.search(
            r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:{})".format(pattern),
            value,
            re.IGNORECASE,
        )
        if match:
            try:
                amount = Decimal(match.group(1).replace(",", "."))
            except InvalidOperation:
                return None
            if amount > 0:
                return amount, unit
    return None


def calculate_run_out_date(medicine):
    medicine = dict(medicine)
    package_size = medicine.get("packageSize")
    package_amount = parse_medicine_amount(package_size)
    if not package_size and medicine.get("productName"):
        package_amount = parse_medicine_amount(medicine["productName"])
    daily_amount = parse_medicine_amount(medicine.get("dailyUsage"))
    if (
        package_amount is None
        or daily_amount is None
        or (
            package_amount[1] is not None
            and daily_amount[1] is not None
            and package_amount[1] != daily_amount[1]
        )
    ):
        return None

    frequency_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:пъти|раза|times?)\b"
        r"|[xх×]\s*(\d+(?:[.,]\d+)?)"
        r"|(\d+(?:[.,]\d+)?)\s*[xх×]",
        medicine["dailyUsage"],
        re.IGNORECASE,
    )
    if frequency_match:
        frequency_value = next(
            group for group in frequency_match.groups() if group is not None
        )
        frequency = Decimal(frequency_value.replace(",", "."))
    else:
        schedule_count = len(
            re.findall(
                r"сутрин|обед|следобед|вечер|нощ(?:ем)?|morning|noon|afternoon|evening|night",
                medicine["dailyUsage"],
                re.IGNORECASE,
            )
        )
        frequency = Decimal(schedule_count or 1)

    quantity = medicine.get("quantity")
    purchase_date_value = medicine.get("purchaseDate")
    if (
        frequency <= 0
        or type(quantity) is not int
        or quantity < 1
        or not isinstance(purchase_date_value, str)
        or not valid_date(purchase_date_value)
    ):
        return None

    daily_usage = daily_amount[0] * frequency
    days_supply = int(
        (
            package_amount[0]
            * medicine["quantity"]
            / daily_usage
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    purchase_date = date.fromisoformat(purchase_date_value)
    return (purchase_date + timedelta(days=days_supply)).isoformat()


def medicine_image_url(medicine):
    return medicine["imageUrl"] or PRODUCT_IMAGE_OVERRIDES.get(medicine["barcode"], "")


def medicine_response(medicine):
    return {
        **dict(medicine),
        "imageUrl": medicine_image_url(medicine),
        "runOutDate": calculate_run_out_date(medicine),
    }


def extract_package_size(product_name):
    if not isinstance(product_name, str):
        return ""
    for label, unit_pattern in PACKAGE_SIZE_PATTERNS:
        count_first = re.search(
            r"(?<!\d)(\d+)\s*(?:№\s*)?(?:{})(?!\w)".format(unit_pattern),
            product_name,
            re.IGNORECASE,
        )
        if count_first:
            return "{} {}".format(count_first.group(1), label)

        unit_first = re.search(
            r"(?:{})(?!\w)\s*(?:[xх×]\s*|№\s*)?(\d+)\b".format(unit_pattern),
            product_name,
            re.IGNORECASE,
        )
        if unit_first:
            return "{} {}".format(unit_first.group(1), label)

        if label == "таблетки" and re.search(
            r"(?:{})".format(unit_pattern), product_name, re.IGNORECASE
        ):
            piece_match = re.search(
                r"(?<!\d)(\d+)\s*(?:№\s*)?(?:бр\.?|броя?\w*|pieces?|pcs)(?!\w)",
                product_name,
                re.IGNORECASE,
            )
            if piece_match:
                return "{} таблетки".format(piece_match.group(1))
    return ""


def normalize_package_size(package_size, product_name):
    if not isinstance(package_size, str) or not isinstance(product_name, str):
        return package_size if isinstance(package_size, str) else ""
    if not re.search(
        r"таблет(?:ка|ки|ок)\w*|табл\.?|tablets?|tabs?",
        product_name,
        re.IGNORECASE,
    ):
        return package_size

    count_match = re.fullmatch(
        r"\s*(\d+)\s*(?:таблет(?:ка|ки|ок)\w*|табл\.?|tablets?|tabs?"
        r"|бр\.?|броя?\w*|pieces?|pcs)?\s*",
        package_size,
        re.IGNORECASE,
    )
    if count_match:
        return "{} таблетки".format(count_match.group(1))
    return package_size


def lookup_barcode_bg(barcode):
    url = "{}?{}".format(
        BARCODE_BG_SEARCH_URL,
        urlencode({"barcode": barcode}),
    )
    lookup_request = Request(
        url,
        headers={"User-Agent": "SemeinaAptechka/1.0 (local family medicine cabinet)"},
    )
    try:
        tls_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(lookup_request, timeout=7, context=tls_context) as response:
            html = response.read().decode("utf-8")
    except HTTPError as error:
        if error.code == 404:
            error.close()
            return BARCODE_BG_SOURCE, None, None
        error.close()
        return BARCODE_BG_SOURCE, None, "HTTP {}".format(error.code)
    except (TimeoutError, URLError, OSError, UnicodeDecodeError) as error:
        logging.getLogger(__name__).warning(
            "Product lookup failed in %s: %s", BARCODE_BG_SOURCE, error
        )
        return BARCODE_BG_SOURCE, None, str(error)

    parser = BarcodeBgResultParser()
    parser.feed(html)
    for row in parser.rows:
        if len(row) < 3 or re.sub(r"\D", "", row[1]) != barcode:
            continue

        product_name = row[2].strip()
        if not product_name:
            continue

        return BARCODE_BG_SOURCE, {
            "found": True,
            "productName": product_name,
            "imageUrl": PRODUCT_IMAGE_OVERRIDES.get(barcode, ""),
            "packageSize": extract_package_size(product_name),
            "source": BARCODE_BG_SOURCE,
        }, None

    return BARCODE_BG_SOURCE, None, None


def validate_medicine(body):
    if not isinstance(body, dict):
        body = {}

    barcode = body.get("barcode")
    barcode = barcode.strip() if isinstance(barcode, str) else ""
    product_name = body.get("productName")
    product_name = product_name.strip() if isinstance(product_name, str) else ""
    daily_usage = body.get("dailyUsage")
    daily_usage = daily_usage.strip() if isinstance(daily_usage, str) else ""
    image_url = body.get("imageUrl")
    package_size = body.get("packageSize")

    if image_url is not None and not isinstance(image_url, str):
        return "Въведете валиден адрес на снимката."
    if package_size is not None and not isinstance(package_size, str):
        return "Въведете валиден размер на опаковката."

    image_url = image_url.strip() if image_url else None
    package_size = package_size.strip() if package_size else None
    quantity = body.get("quantity")

    if not BARCODE_PATTERN.fullmatch(barcode):
        return "Баркодът трябва да съдържа 8, 12, 13 или 14 цифри."
    if not 1 <= len(product_name) <= 160:
        return "Името трябва да е до 160 символа."
    if type(quantity) is not int or not 1 <= quantity <= 99999:
        return "Количеството трябва да е цяло число между 1 и 99 999."
    purchase_date = body.get("purchaseDate")
    if not valid_date(purchase_date):
        return "Въведете валидна дата на покупка."
    if not 1 <= len(daily_usage) <= 200:
        return "Дневният прием трябва да е до 200 символа."
    if image_url:
        parsed_url = urlparse(image_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            return "Въведете валиден HTTPS адрес на снимката."
    if package_size and len(package_size) > 80:
        return "Размерът на опаковката трябва да е до 80 символа."

    return {
        "barcode": barcode,
        "productName": product_name,
        "imageUrl": image_url,
        "packageSize": package_size,
        "quantity": quantity,
        "purchaseDate": purchase_date,
        "dailyUsage": daily_usage,
    }


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            os.fspath(current_app.config["DATABASE"]),
            timeout=5,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def initialize_database(app):
    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(os.fspath(database_path))
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
                barcode TEXT NOT NULL CHECK(
                    length(barcode) IN (8, 12, 13, 14)
                    AND barcode NOT GLOB '*[^0-9]*'
                ),
                product_name TEXT NOT NULL CHECK(length(product_name) BETWEEN 1 AND 160),
                image_url TEXT,
                package_size TEXT,
                quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99999),
                purchase_date TEXT NOT NULL,
                daily_usage TEXT NOT NULL CHECK(length(daily_usage) BETWEEN 1 AND 200),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS medicines_member_id ON medicines(member_id);
            """
        )
    finally:
        connection.close()


def lookup_public_catalog(barcode, catalog):
    source, host = catalog
    url = "https://{}/api/v2/product/{}.json?{}".format(
        host,
        barcode,
        urlencode({"fields": "product_name,image_front_url,quantity"}),
    )
    lookup_request = Request(
        url,
        headers={"User-Agent": "SemeinaAptechka/1.0 (local family medicine cabinet)"},
    )
    try:
        tls_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(lookup_request, timeout=7, context=tls_context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            error.close()
            return source, None, None
        error.close()
        return source, None, "HTTP {}".format(error.code)
    except (TimeoutError, URLError, OSError) as error:
        logging.getLogger(__name__).warning(
            "Product lookup failed in %s: %s", source, error
        )
        return source, None, str(error)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        logging.getLogger(__name__).warning(
            "Product lookup returned invalid data from %s: %s", source, error
        )
        return source, None, str(error)

    if not isinstance(data, dict):
        return source, None, "Invalid catalog response"
    product = data.get("product")
    if data.get("status") != 1 or not isinstance(product, dict):
        return source, None, None

    image_url = product.get("image_front_url")
    if not isinstance(image_url, str) or not image_url.startswith("https://"):
        image_url = ""
    product_name = product.get("product_name")
    package_size = product.get("quantity")
    return source, {
        "found": True,
        "productName": product_name if isinstance(product_name, str) else "",
        "imageUrl": image_url,
        "packageSize": package_size if isinstance(package_size, str) else "",
        "source": source,
    }, None


def create_app(test_config=None):
    app = Flask(__name__, static_folder=os.fspath(BASE_DIR / "public"), static_url_path="")
    app.config.from_mapping(
        DATABASE=os.fspath(BASE_DIR / "data" / "medicine-cabinet.sqlite"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    initialize_database(app)

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(BadRequest)
    def handle_bad_request(error):
        if request.path.startswith("/api/"):
            return api_error("Невалиден JSON формат.", 400)
        return error

    @app.errorhandler(UnsupportedMediaType)
    def handle_unsupported_media_type(error):
        if request.path.startswith("/api/"):
            return api_error("Заявката трябва да съдържа JSON данни.", 415)
        return error

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return api_error("Непозната или невалидна API заявка.", error.code)
        return error

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Request failed", exc_info=error)
        if request.path.startswith("/api/"):
            return api_error("Възникна вътрешна грешка.", 500)
        return "Възникна вътрешна грешка.", 500

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/family")
    def list_family():
        members = get_db().execute(
            """
            SELECT f.id, f.name, COUNT(m.id) AS medicine_count
            FROM family_members f
            LEFT JOIN medicines m ON m.member_id = f.id
            GROUP BY f.id
            ORDER BY f.id
            """
        ).fetchall()
        return jsonify([dict(member) for member in members])

    @app.get("/api/overview")
    def get_overview():
        db = get_db()
        members = db.execute(
            """
            SELECT f.id, f.name, COUNT(m.id) AS medicine_count
            FROM family_members f
            LEFT JOIN medicines m ON m.member_id = f.id
            GROUP BY f.id
            ORDER BY f.id
            """
        ).fetchall()
        medicine_rows = db.execute(
            """
            SELECT id, member_id AS memberId, barcode,
                   product_name AS productName, image_url AS imageUrl,
                   package_size AS packageSize, quantity,
                   purchase_date AS purchaseDate, daily_usage AS dailyUsage
            FROM medicines
            ORDER BY member_id, purchase_date DESC, id DESC
            """
        ).fetchall()
        medicines_by_member = {member["id"]: [] for member in members}
        for medicine in medicine_rows:
            medicines_by_member[medicine["memberId"]].append(
                medicine_response(medicine)
            )

        return jsonify(
            {
                "members": [dict(member) for member in members],
                "medicines": [
                    {"memberId": member["id"], "medicines": medicines_by_member[member["id"]]}
                    for member in members
                ],
            }
        )

    @app.post("/api/family")
    def add_family_member():
        body = request.get_json()
        name = body.get("name") if isinstance(body, dict) else None
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 80:
            return api_error("Името трябва да е между 1 и 80 символа.", 400)

        db = get_db()
        existing_names = db.execute(
            "SELECT name FROM family_members"
        ).fetchall()
        if any(member["name"].casefold() == name.casefold() for member in existing_names):
            return api_error("Член на семейството с това име вече съществува.", 409)

        cursor = db.execute(
            "INSERT INTO family_members (name) VALUES (?)",
            (name,),
        )
        db.commit()
        return jsonify(
            {"id": cursor.lastrowid, "name": name, "medicine_count": 0}
        ), 201

    @app.delete("/api/family/<member_id>")
    def delete_family_member(member_id):
        parsed_id = parse_positive_integer(member_id)
        if parsed_id is None:
            return api_error("Невалиден член на семейството.", 400)
        cursor = get_db().execute(
            "DELETE FROM family_members WHERE id = ?",
            (parsed_id,),
        )
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Членът на семейството не е намерен.", 404)
        return "", 204

    @app.get("/api/medicines")
    def list_medicines():
        member_id = parse_positive_integer(request.args.get("memberId"))
        if member_id is None:
            return api_error("Изберете член на семейството.", 400)
        db = get_db()
        member = db.execute(
            "SELECT id FROM family_members WHERE id = ?",
            (member_id,),
        ).fetchone()
        if member is None:
            return api_error("Членът на семейството не е намерен.", 404)

        medicines = db.execute(
            """
            SELECT id, member_id AS memberId, barcode,
                   product_name AS productName, image_url AS imageUrl,
                   package_size AS packageSize, quantity,
                   purchase_date AS purchaseDate, daily_usage AS dailyUsage
            FROM medicines
            WHERE member_id = ?
            ORDER BY purchase_date DESC, id DESC
            """,
            (member_id,),
        ).fetchall()
        return jsonify([medicine_response(medicine) for medicine in medicines])

    @app.post("/api/medicines")
    def add_medicine():
        body = request.get_json()
        body = body if isinstance(body, dict) else {}
        member_id = parse_positive_integer(body.get("memberId"))
        if member_id is None:
            return api_error("Изберете член на семейството.", 400)

        db = get_db()
        member = db.execute(
            "SELECT id FROM family_members WHERE id = ?",
            (member_id,),
        ).fetchone()
        if member is None:
            return api_error("Членът на семейството не е намерен.", 404)

        medicine = validate_medicine(body)
        if isinstance(medicine, str):
            return api_error(medicine, 400)

        cursor = db.execute(
            """
            INSERT INTO medicines
                (member_id, barcode, product_name, image_url, package_size,
                 quantity, purchase_date, daily_usage)
            VALUES
                (:memberId, :barcode, :productName, :imageUrl, :packageSize,
                 :quantity, :purchaseDate, :dailyUsage)
            """,
            {"memberId": member_id, **medicine},
        )
        db.commit()
        return jsonify(
            {
                "id": cursor.lastrowid,
                "memberId": member_id,
                **medicine,
                "imageUrl": medicine_image_url(medicine),
                "runOutDate": calculate_run_out_date(medicine),
            }
        ), 201

    @app.delete("/api/medicines/<medicine_id>")
    def delete_medicine(medicine_id):
        parsed_id = parse_positive_integer(medicine_id)
        if parsed_id is None:
            return api_error("Невалидно лекарство.", 400)
        cursor = get_db().execute(
            "DELETE FROM medicines WHERE id = ?",
            (parsed_id,),
        )
        get_db().commit()
        if cursor.rowcount == 0:
            return api_error("Лекарството не е намерено.", 404)
        return "", 204

    @app.patch("/api/medicines/<medicine_id>/image")
    def update_medicine_image(medicine_id):
        parsed_id = parse_positive_integer(medicine_id)
        if parsed_id is None:
            return api_error("Невалидно лекарство.", 400)

        body = request.get_json()
        image_url = body.get("imageUrl") if isinstance(body, dict) else None
        image_url = image_url.strip() if isinstance(image_url, str) else ""
        parsed_url = urlparse(image_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            return api_error("Въведете валиден HTTPS адрес на снимката.", 400)

        db = get_db()
        db.execute(
            """
            UPDATE medicines
            SET image_url = ?
            WHERE id = ? AND (image_url IS NULL OR image_url = '')
            """,
            (image_url, parsed_id),
        )
        db.commit()
        medicine = db.execute(
            "SELECT id, image_url AS imageUrl FROM medicines WHERE id = ?",
            (parsed_id,),
        ).fetchone()
        if medicine is None:
            return api_error("Лекарството не е намерено.", 404)
        return jsonify(dict(medicine))

    @app.get("/api/lookup/<barcode>")
    def lookup_product(barcode):
        if not BARCODE_PATTERN.fullmatch(barcode):
            return api_error("Баркодът трябва да съдържа 8, 12, 13 или 14 цифри.", 400)

        results = {}
        with ThreadPoolExecutor(max_workers=len(PRODUCT_CATALOGS) + 1) as executor:
            futures = [
                executor.submit(lookup_public_catalog, barcode, catalog)
                for catalog in PRODUCT_CATALOGS
            ]
            futures.append(executor.submit(lookup_barcode_bg, barcode))
            for future in as_completed(futures):
                source, product, error = future.result()
                results[source] = (product, error)

        sources = (BARCODE_BG_SOURCE,) + tuple(
            source for source, _host in PRODUCT_CATALOGS
        )
        products = [
            results[source][0]
            for source in sources
            if results[source][0]
        ]
        if products:
            barcode_bg_product = next(
                (
                    product for product in products
                    if product["source"] == BARCODE_BG_SOURCE
                ),
                None,
            )
            product = barcode_bg_product or next(
                (product for product in products if product["imageUrl"]),
                products[0],
            )
            if not product["imageUrl"]:
                product = {
                    **product,
                    "imageUrl": next(
                        (
                            match["imageUrl"] for match in products
                            if match["imageUrl"]
                        ),
                        "",
                    ),
                }
            package_size = product["packageSize"]
            if not package_size:
                package_size = next(
                    (
                        match["packageSize"]
                        for match in products
                        if match["packageSize"]
                    ),
                    "",
                )
                if not package_size:
                    package_size = next(
                        (
                            size
                            for match in products
                            if (size := extract_package_size(match["productName"]))
                        ),
                        "",
                    )
            package_size = normalize_package_size(
                package_size,
                product["productName"],
            )
            product = {**product, "packageSize": package_size}
            return jsonify(product)

        if all(error for _product, error in results.values()):
            app.logger.warning(
                "Product lookup failed in all public catalogs for barcode %s",
                barcode,
            )
            return api_error(
                "Не успяхме да достигнем публичните продуктови каталози. Опитай отново.",
                502,
            )

        unavailable_sources = [
            source for source in sources if results[source][1]
        ]
        message = (
            "Продуктът не е намерен в достъпните публични каталози."
            if unavailable_sources
            else "Продуктът не е намерен в проверените публични каталози."
        )
        return jsonify(
            {
                "found": False,
                "message": message + " Можеш да попълниш данните ръчно.",
                "sourcesSearched": list(sources),
                "sourcesUnavailable": unavailable_sources,
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    print("Семейна аптечка е достъпна на http://localhost:{}".format(port))
    app.run(host="127.0.0.1", port=port, debug=False)
