from ras_commander.results.ResultsParser import ResultsParser

COMPLETED = "Complete Process\t    1:26\n"


def test_hec_ras_61_write_attribute_precheck_notice_is_a_warning():
    messages = ("Writing Plan GIS Data...\n"
                "WRITE ATTR ERROR: ERROR: Geometry/River Edge Lines not found in WriteAttributePreCheck\n"
                + COMPLETED)
    parsed = ResultsParser.parse_compute_messages(messages)
    assert parsed["completed"] and not parsed["has_errors"]
    assert [d["reason_code"] for d in parsed["diagnostics"]] == [
        "hec_ras_write_attribute_precheck_missing_geometry_layer"]


def test_other_write_attribute_errors_still_fail():
    messages = "WRITE ATTR ERROR: ERROR: could not write Results/Unsteady\n" + COMPLETED
    assert ResultsParser.parse_compute_messages(messages)["has_errors"]
