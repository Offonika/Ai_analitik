from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extensions" / "offonika"
SOURCE = EXTENSION / "src"


def test_onec_extension_declares_only_readonly_http_methods() -> None:
    service = ET.parse(SOURCE / "HTTPServices" / "WBUnitEconomics.xml")
    methods = [
        element.text
        for element in service.findall(".//{http://v8.1c.ru/8.3/MDClasses}HTTPMethod")
    ]

    assert methods == ["GET", "GET"]


def test_onec_extension_xml_sources_are_well_formed() -> None:
    xml_files = sorted(SOURCE.rglob("*.xml"))

    assert xml_files
    for xml_file in xml_files:
        ET.parse(xml_file)


def test_onec_extension_configuration_local_strings_are_structured() -> None:
    configuration = ET.parse(SOURCE / "Configuration.xml")
    namespace = {"md": "http://v8.1c.ru/8.3/MDClasses"}

    for tag_name in ("BriefInformation",):
        element = configuration.find(f".//md:{tag_name}", namespace)

        assert element is not None
        assert (element.text or "").strip() == ""
        assert len(list(element)) > 0


def test_onec_extension_uses_base_russian_language() -> None:
    configuration = ET.parse(SOURCE / "Configuration.xml")
    namespace = {"md": "http://v8.1c.ru/8.3/MDClasses"}

    default_language = configuration.find(
        ".//md:Properties/md:DefaultLanguage",
        namespace,
    )
    language_child = configuration.find(".//md:ChildObjects/md:Language", namespace)

    assert default_language is not None
    assert default_language.text == "Language.Русский"
    assert language_child is None


def test_onec_extension_role_has_no_write_rights() -> None:
    rights = ET.parse(
        SOURCE
        / "Roles"
        / "offonika_ТолькоЧтение"
        / "Ext"
        / "Rights.xml"
    )
    right_names = {
        element.text
        for element in rights.findall(".//{http://v8.1c.ru/8.2/roles}right/{http://v8.1c.ru/8.2/roles}name")
    }

    assert {"Insert", "Update", "Delete", "Post", "InteractiveInsert"}.isdisjoint(
        right_names
    )
    assert {"Read", "View"}.issubset(right_names)


def test_onec_extension_role_rights_do_not_reference_cross_extension_objects() -> None:
    rights = (
        SOURCE
        / "Roles"
        / "offonika_ТолькоЧтение"
        / "Ext"
        / "Rights.xml"
    ).read_text(encoding="utf-8")

    assert "ИС_WB_" not in rights


def test_onec_extension_module_has_no_privileged_or_object_write_calls() -> None:
    module = (
        SOURCE / "HTTPServices" / "WBUnitEconomics" / "Ext" / "Module.bsl"
    ).read_text(encoding="utf-8")

    forbidden_fragments = [
        "УстановитьПривилегированныйРежим",
        ".Записать(",
        ".Удалить(",
        ".Провести(",
        "Новый ЗаписьНабора",
        "Новый НаборЗаписей",
    ]

    for fragment in forbidden_fragments:
        assert fragment not in module


def test_onec_extension_source_contains_only_expected_metadata_objects() -> None:
    files = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }

    assert files == {
        "Configuration.xml",
        "HTTPServices/WBUnitEconomics.xml",
        "HTTPServices/WBUnitEconomics/Ext/Module.bsl",
        "Roles/offonika_ТолькоЧтение.xml",
        "Roles/offonika_ТолькоЧтение/Ext/Rights.xml",
    }
