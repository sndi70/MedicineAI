from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent / "MedicineAI_AI_Assisted_Development_Exam.docx"
EVIDENCE = Path(__file__).resolve().parent / "evidence"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"

for prefix, namespace in (("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC)):
    ET.register_namespace(prefix, namespace)


def element(parent, tag, namespace=W, attributes=None):
    node = ET.SubElement(parent, "{{{}}}{}".format(namespace, tag))
    for key, value in (attributes or {}).items():
        if namespace == W and not key.startswith("{"):
            key = "{{{}}}{}".format(W, key)
        node.set(key, str(value))
    return node


def paragraph(parent, text="", style="Normal", bold=False, italic=False, align=None):
    para = element(parent, "p")
    properties = element(para, "pPr")
    element(properties, "pStyle", attributes={"val": style})
    if align:
        element(properties, "jc", attributes={"val": align})
    run = element(para, "r")
    run_properties = element(run, "rPr")
    if bold:
        element(run_properties, "b")
    if italic:
        element(run_properties, "i")
    text_node = element(run, "t")
    if text[:1].isspace() or text[-1:].isspace():
        text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text
    return para


def hyperlink(parent, text, relationship_id):
    para = element(parent, "p")
    properties = element(para, "pPr")
    element(properties, "pStyle", attributes={"val": "Normal"})
    link = element(para, "hyperlink", attributes={"{{{}}}id".format(R): relationship_id})
    run = element(link, "r")
    run_properties = element(run, "rPr")
    element(run_properties, "color", attributes={"val": "28785F"})
    element(run_properties, "u", attributes={"val": "single"})
    element(run, "t").text = text


def image_paragraph(parent, filename, relationship_id, width_inches):
    path = EVIDENCE / filename
    data = path.read_bytes()
    width_px = int.from_bytes(data[16:20], "big")
    height_px = int.from_bytes(data[20:24], "big")
    width = int(width_inches * 914400)
    height = int(width * height_px / width_px)

    para = element(parent, "p")
    properties = element(para, "pPr")
    element(properties, "jc", attributes={"val": "center"})
    run = element(para, "r")
    drawing = element(run, "drawing")
    inline = element(drawing, "inline", WP, {"distT": 0, "distB": 0, "distL": 0, "distR": 0})
    element(inline, "extent", WP, {"cx": width, "cy": height})
    element(inline, "docPr", WP, {"id": 1 if relationship_id == "rId2" else 2, "name": filename})
    graphic = element(inline, "graphic", A)
    graphic_data = element(graphic, "graphicData", A, {"uri": PIC})
    picture = element(graphic_data, "pic", PIC)
    non_visual = element(picture, "nvPicPr", PIC)
    element(non_visual, "cNvPr", PIC, {"id": 0, "name": filename})
    element(non_visual, "cNvPicPr", PIC)
    fill = element(picture, "blipFill", PIC)
    element(fill, "blip", A, {"{{{}}}embed".format(R): relationship_id})
    stretch = element(fill, "stretch", A)
    element(stretch, "fillRect", A)
    shape = element(picture, "spPr", PIC)
    transform = element(shape, "xfrm", A)
    element(transform, "off", A, {"x": 0, "y": 0})
    element(transform, "ext", A, {"cx": width, "cy": height})
    geometry = element(shape, "prstGeom", A, {"prst": "rect"})
    element(geometry, "avLst", A)


def page_break(parent):
    para = element(parent, "p")
    run = element(para, "r")
    element(run, "br", attributes={"{{{}}}type".format(W): "page"})


pages = [
    [
        ("title", "AI-Assisted Development Exam"),
        ("subtitle", "Family Medicine Register"),
        ("body", "A small local-first web application for recording family medicine purchases, viewing stock, and estimating when a package may run out."),
        ("heading", "Project idea and system requirements"),
        ("body", "The Family Medicine Register helps a household keep a separate medicine inventory for each family member. A user can create and remove profiles, add medicine purchases, find product details by barcode, and review estimated stock reminders in one browser interface."),
        ("bullet", "Family profiles and medicine records are stored in a local SQLite database and managed through a Flask web API."),
        ("bullet", "A barcode lookup checks Barcode.bg and public product catalogs for a product name, image, and package size; product details can still be entered manually."),
        ("bullet", "The interface displays the product image, barcode, purchase quantity/date, daily usage, and an estimated run-out reminder when units can be matched."),
        ("bullet", "Family names are unique without regard to case, including Cyrillic case variants. Removing a family profile also removes its associated medicine records."),
        ("heading", "Scope and safety"),
        ("body", "This is a local household record, not a medical dosing or prescribing system. Run-out dates are estimates derived from user-entered quantities, package size, daily usage, and purchase date. They do not track doses actually taken and should be checked against the real package and usage."),
        ("heading", "Technology and project reference"),
        ("body", "Python, Flask, SQLite, browser-native JavaScript, HTML, and CSS. Development used GitHub Copilot in VS Code with iterative prompts, code review, tests, and browser validation."),
        ("body", "Repository: https://github.com/sndi70/MedicineAI"),
        ("body", "Evidence and test results in this document were captured from the working application and its current test suite."),
    ],
    [
        ("heading1", "System architecture — modules"),
        ("body", "Browser UI  ⇄  Flask JSON API  ⇄  SQLite database\n                               ⇅\n                   Barcode and product catalogs"),
        ("body", "The server validates input and owns persistence and inventory calculations. The browser renders profiles and medicine cards, calls the API, and presents lookup results and reminders. External catalog failures are surfaced rather than treated as reliable product data."),
        ("heading", "Module 1 — Flask API and validation"),
        ("body", "Approach & reasoning: Keep data rules on the server so browser forms and API clients receive consistent validation. Use explicit JSON routes for profiles, medicines, overview data, images, and barcode lookup."),
        ("body", "Workflow: Asked Copilot to add the API behavior; inspected route and error handling; refined it with regression tests for invalid input, duplicate names, CRUD, and compatibility with existing routes."),
        ("body", "Testing strategy: Flask’s test client exercises successful and rejected requests, returned JSON shapes, HTTP status codes, and deletion behavior. Current full suite: 27 tests pass."),
        ("body", "AI tool choice: GitHub Copilot in VS Code provided code-aware implementation suggestions and helped iterate against the existing Flask patterns."),
        ("body", "Representative prompt: “Forbid creation of a new member with a name that already exists.” Follow-up testing exposed SQLite NOCASE’s ASCII-only behavior; the implementation now compares Python Unicode casefolded names."),
        ("heading", "Module 2 — SQLite persistence"),
        ("body", "Approach & reasoning: Keep the application local-first and dependency-light. SQLite stores family profiles and medicine purchases; profile deletion cascades to its medicines. The database is initialized automatically and lives under the ignored data/ directory."),
        ("body", "Workflow: Asked Copilot to connect application routes to the existing SQLite schema; verified overview and CRUD responses; preserved the existing database filename so existing local data remains usable."),
        ("body", "Testing strategy: Temporary databases isolate unit tests. Tests cover create/list/delete operations, profile-to-medicine relationships, and the combined overview endpoint."),
        ("body", "AI tool choice: GitHub Copilot in VS Code was used to make small changes in the existing Flask/SQLite structure and generate focused regression tests."),
        ("body", "Representative prompt: “Keep the medicine records separated by family member and allow a member to be removed.”"),
    ],
    [
        ("heading1", "Development process per module"),
        ("heading", "Module 3 — Barcode lookup and product enrichment"),
        ("body", "Approach & reasoning: Barcode values identify candidates, not guaranteed medicine facts. Query Barcode.bg alongside Open Facts catalogs, prefer matching Barcode.bg product details where available, and retain fallback product images or package-size data from other catalogs. Allow manual entry when the lookup misses."),
        ("body", "Workflow: Asked Copilot to add Barcode.bg, combine catalog responses, extract package counts from product names, and display a medicine image rather than its URL. Verified known barcode cases and the live lookup response."),
        ("body", "Testing strategy: Mock catalog HTTP responses to test matching barcode rows, fallback data, network failures, and package-size extraction. The live Nebilet lookup returns “28 таблетки” for barcode 4013054002162."),
        ("body", "AI tool choice: GitHub Copilot in VS Code supported implementation and test iteration. Browser review confirmed the populated image preview and package-size field."),
        ("body", "Representative prompts: “Always check barcode in Barcode.bg.” “Look up package size automatically.”"),
        ("heading", "Module 4 — Inventory estimates and reminders"),
        ("body", "Approach & reasoning: Calculate a calendar run-out date only when package quantity and daily usage can be interpreted in compatible units. Multiply package size by purchased package count, account for daily frequency, and start from purchase date. Display a persistent card warning when the estimated date is within three days or has passed."),
        ("body", "Workflow: Asked Copilot for a three-day warning based on package size, daily usage, quantity, and buying date. Iteratively corrected bare-number inputs and package counts inferred from names, then checked visible UI warnings."),
        ("body", "Testing strategy: Unit tests cover expected dates, frequency, unit mismatch, quantities, purchase dates, and package-size extraction. Browser review confirmed the warning is present on the corresponding medicine card."),
        ("body", "AI tool choice: GitHub Copilot in VS Code helped trace the calculation from stored fields to API output and visible warning; tests were used to validate date math."),
        ("body", "Representative prompt: “Add notification 3 days before medicine quantity ending based on quantity, daily usage and buying date.”"),
    ],
    [
        ("heading1", "Modules, challenges, and tool comparison"),
        ("heading", "Module 5 — Browser interface"),
        ("body", "Approach & reasoning: Use browser-native JavaScript and accessible HTML controls to keep the app small and easy to run. The interface renders family selection, medicine cards, barcode search, dialogs, image previews, warnings, and visible error messages."),
        ("body", "Workflow: Asked Copilot to add the requested interaction; reloaded the running app and inspected actual content in the browser; adjusted behavior from user feedback (for example, previewing the product image and sorting stock by estimated run-out date)."),
        ("body", "Testing strategy: Manual browser checks verified profile selection, populated medicine cards, image display, search, form lookup, package-size value, and warnings. API and business rules are covered by unit tests."),
        ("body", "AI tool choice: GitHub Copilot in VS Code was useful because code changes and browser/test feedback could be handled in the same development workflow."),
        ("body", "Representative prompt: “When adding medicine, show the medicine picture instead of its address.”"),
        ("heading", "Module 6 — Automated tests and verification"),
        ("body", "Approach & reasoning: Add regression tests around behavior that can silently fail: unit/date calculations, barcode parsing, duplicate Cyrillic names, and data relationships. Keep external network tests deterministic by mocking catalog responses."),
        ("body", "Workflow: Asked Copilot to add regression tests alongside features; ran the full unittest suite after changes; used live browser/API checks for end-to-end behavior."),
        ("body", "Testing strategy: `python -m unittest discover -s tests` currently reports 27 passing tests. `py_compile` and `git diff --check` were also used after Python changes."),
        ("body", "AI tool choice: GitHub Copilot in VS Code accelerated test scaffolding; the Python unittest runner provided the pass/fail evidence."),
        ("body", "Representative interaction: “Add tests for exact and case-differing duplicate family names.”"),
        ("heading", "Key prompts or interactions"),
        ("body", "Selected prompts, lightly edited for readability:"),
        ("bullet", "“Add a persistent warning three days before medicine stock runs out, based on package size, daily usage, quantity, and purchase date.”"),
        ("bullet", "“Always check Barcode.bg when searching by barcode, while keeping other catalogs as fallbacks.”"),
        ("bullet", "“Look up the package size automatically, and show the medicine picture instead of its URL in the add form.”"),
        ("bullet", "“Prevent creating a family member whose name matches an existing member, including capitalization variants.”"),
        ("bullet", "“Add regression tests for exact and case-differing duplicate names.”"),
        ("heading", "Challenges & tool comparison"),
        ("body", "The hardest issue was inconsistent catalog data: package counts may appear as “28 бр.”, tablet counts may be embedded in a product name, and external services can be unavailable. The UI therefore permits manual entry and does not assume every lookup is complete. Another challenge was Unicode-aware uniqueness: SQLite NOCASE did not equate Bulgarian Cyrillic case variants, so server-side Unicode casefold comparison was needed."),
        ("body", "GitHub Copilot was the most useful tool in this project because it was integrated with the VS Code workspace and supported an iterative loop of implementation, tests, and browser inspection. I did not perform a controlled comparison with Claude Code, Augment Code, or Cursor, so this is a project-specific assessment rather than a benchmark."),
        ("body", "If continuing: add encrypted backup/export and restore, track actual doses or stock adjustments, broaden tests for catalog edge cases, and add authentication before any remote or multi-user deployment. Reminder dates remain informational estimates."),
    ],
    [
        ("heading1", "Working system evidence"),
        ("body", "The following screenshots were captured from the running local application on 30 October 2026. Sample profile labels are abbreviated in the test data."),
        ("caption", "Figure 1. Medicine inventory with product images and an estimated run-out warning."),
        ("image", ("01-medicine-register.png", "rId2", 4.8)),
        ("caption", "Figure 2. Barcode 4013054002162 fills the product name and package count (“28 таблетки”) in the add-medicine form."),
        ("image", ("02-barcode-package-lookup.png", "rId3", 4.8)),
        ("heading", "Repository and verification"),
        ("body", "Source code: https://github.com/sndi70/MedicineAI"),
        ("body", "Verified test result: 27 tests passed using the project’s unittest suite. The live barcode lookup endpoint returned the Nebilet product and “28 таблетки”; the browser showed the corresponding populated form."),
    ],
]


def build_document():
    document = ET.Element("{{{}}}document".format(W))
    body = element(document, "body")

    for page_index, blocks in enumerate(pages):
        if page_index:
            page_break(body)
        for kind, value in blocks:
            if kind in {"title", "subtitle", "heading", "heading1", "body", "bullet", "caption"}:
                if value == "Repository: https://github.com/sndi70/MedicineAI":
                    paragraph(body, "Repository:")
                    hyperlink(body, "https://github.com/sndi70/MedicineAI", "rId4")
                    continue
                styles = {
                    "title": "Title",
                    "subtitle": "Subtitle",
                    "heading": "Heading2",
                    "heading1": "Heading1",
                    "body": "Normal",
                    "bullet": "Normal",
                    "caption": "Caption",
                }
                text = "- " + value if kind == "bullet" else value
                para = paragraph(body, text, style=styles[kind], italic=kind == "caption")
                if kind in {"title", "subtitle", "heading", "heading1", "caption"}:
                    p_properties = para.find("{{{}}}pPr".format(W))
                    element(p_properties, "keepNext")
            elif kind == "image":
                image_paragraph(body, value[0], value[1], value[2])

    section = element(body, "sectPr")
    element(section, "pgSz", attributes={"w": 12240, "h": 15840})
    element(section, "pgMar", attributes={"top": 720, "right": 900, "bottom": 720, "left": 900, "header": 360, "footer": 360, "gutter": 0})

    styles = ET.Element("{{{}}}styles".format(W))
    defaults = element(styles, "docDefaults")
    run_defaults = element(defaults, "rPrDefault")
    run_properties = element(run_defaults, "rPr")
    element(run_properties, "rFonts", attributes={"ascii": "Aptos", "hAnsi": "Aptos", "eastAsia": "Aptos", "cs": "Aptos"})
    element(run_properties, "sz", attributes={"val": 19})
    element(run_properties, "color", attributes={"val": "24342F"})
    paragraph_defaults = element(element(defaults, "pPrDefault"), "pPr")
    spacing = element(paragraph_defaults, "spacing", attributes={"after": 90, "line": 250, "lineRule": "auto"})

    style_specs = {
        "Normal": (None, 19, "24342F", False, 0, 90),
        "Title": (None, 34, "205B46", True, 0, 110),
        "Subtitle": (None, 25, "477B65", True, 0, 180),
        "Heading1": (None, 27, "205B46", True, 0, 150),
        "Heading2": (None, 22, "27785F", True, 180, 90),
        "Caption": (None, 16, "64736C", False, 40, 100),
    }
    for name, (based_on, size, color, is_bold, before, after) in style_specs.items():
        style = element(styles, "style", attributes={"type": "paragraph", "styleId": name})
        element(style, "name", attributes={"val": name})
        if based_on:
            element(style, "basedOn", attributes={"val": based_on})
        style_ppr = element(style, "pPr")
        element(style_ppr, "spacing", attributes={"before": before, "after": after, "line": 250, "lineRule": "auto"})
        style_rpr = element(style, "rPr")
        element(style_rpr, "rFonts", attributes={"ascii": "Aptos", "hAnsi": "Aptos"})
        element(style_rpr, "sz", attributes={"val": size})
        element(style_rpr, "color", attributes={"val": color})
        if is_bold:
            element(style_rpr, "b")

    content_types = ET.Element("{{{}}}Types".format(CT))
    element(content_types, "Default", CT, {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    element(content_types, "Default", CT, {"Extension": "xml", "ContentType": "application/xml"})
    element(content_types, "Default", CT, {"Extension": "png", "ContentType": "image/png"})
    element(content_types, "Override", CT, {"PartName": "/word/document.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"})
    element(content_types, "Override", CT, {"PartName": "/word/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"})

    package_rels = ET.Element("{{{}}}Relationships".format(REL))
    element(package_rels, "Relationship", REL, {
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": "word/document.xml",
    })
    document_rels = ET.Element("{{{}}}Relationships".format(REL))
    for rel_id, rel_type, target, mode in (
        ("rId1", "styles", "styles.xml", None),
        ("rId2", "image", "media/image1.png", None),
        ("rId3", "image", "media/image2.png", None),
        ("rId4", "hyperlink", "https://github.com/sndi70/MedicineAI", "External"),
    ):
        attributes = {
            "Id": rel_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/{}".format(rel_type),
            "Target": target,
        }
        if mode:
            attributes["TargetMode"] = mode
        element(document_rels, "Relationship", REL, attributes)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ET.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ET.tostring(package_rels, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", ET.tostring(styles, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/_rels/document.xml.rels", ET.tostring(document_rels, encoding="utf-8", xml_declaration=True))
        archive.write(EVIDENCE / "01-medicine-register.png", "word/media/image1.png")
        archive.write(EVIDENCE / "02-barcode-package-lookup.png", "word/media/image2.png")


if __name__ == "__main__":
    build_document()
