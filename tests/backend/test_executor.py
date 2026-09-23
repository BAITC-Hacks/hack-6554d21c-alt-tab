import json
import re

import pytest

from backend.catalog import Catalog
from backend.config import ROOT
from backend.executor import ActionError, Executor


@pytest.fixture(scope="module")
def catalog():
    return Catalog()


@pytest.fixture
def ex(catalog):
    return Executor(catalog)


@pytest.fixture
def data(catalog):
    return catalog.new_mock_state()


def test_ogpo_price_almaty_unknown_driver(ex, data):
    out = ex.run("calc_ogpo_price", {"region": "almaty", "vehicle_type": "car",
                                     "drivers_iin": ["000000000000"]}, data)
    assert out == {"price": 38000, "bm_class": "3"}


def test_ogpo_price_uses_worst_driver_class(ex, data):
    out = ex.run("calc_ogpo_price", {"region": "astana", "vehicle_type": "truck",
                                     "drivers_iin": ["880126300907", "890922300345"]}, data)
    assert out["bm_class"] == "1" and out["price"] == int(34000 * 1.4 * 1.2)


def test_travel_price_turkey(ex, data):
    out = ex.run("calc_travel_price", {"trip_country": "Turkey", "trip_start": "2026-10-10", "trip_end": "2026-10-16",
                                       "travelers_count": 2, "traveler_max_age": 42}, data)
    assert out["price"] == 15400 and out["zone"] == "C" and out["coverage"] == "50 000 USD"


def test_travel_zones_and_limits(ex, data):
    base = {"trip_start": "2026-10-10", "trip_end": "2026-10-10", "travelers_count": 1, "traveler_max_age": 30}
    assert ex.run("calc_travel_price", dict(base, trip_country="Германия"), data)["zone"] == "B"
    assert ex.run("calc_travel_price", dict(base, trip_country="USA"), data)["zone"] == "D"
    assert ex.run("calc_travel_price", dict(base, trip_country="Georgia"), data)["zone"] == "A"
    with pytest.raises(ActionError) as err:
        ex.run("calc_travel_price", dict(base, trip_country="Turkey", traveler_max_age=80), data)
    assert err.value.code == "not_eligible"
    with pytest.raises(ActionError) as err:
        ex.run("calc_travel_price", dict(base, trip_country="Turkey", trip_start="2026-09-01"), data)
    assert err.value.code == "invalid_input"


def test_casco_price_and_age_limit(ex, data):
    out = ex.run("calc_casco_price", {"car_value": 10000000, "car_year": 2020, "franchise": 50000}, data)
    assert out["price"] == int(10000000 * 0.05 * 0.9)
    with pytest.raises(ActionError) as err:
        ex.run("calc_casco_price", {"car_value": 3000000, "car_year": 2010, "franchise": 0}, data)
    assert err.value.code == "not_eligible"


def test_property_and_accident_prices(ex, data):
    assert ex.run("calc_property_price", {"property_type": "house", "sum_insured": 10000000}, data)["price"] == 37500
    assert ex.run("calc_accident_price", {"sum_insured": 3000000}, data)["price"] == 15000
    with pytest.raises(ActionError) as err:
        ex.run("calc_accident_price", {"sum_insured": 777}, data)
    assert err.value.code == "invalid_input"


def test_cancel_policy_refund_and_repeat(ex, data):
    out = ex.run("cancel_policy", {"policy_number": "SQ-CASCO-204350", "cancel_reason": "продал машину"}, data)
    assert out["refund_amount"] == 163800
    policy = next(p for p in data["policies"] if p["policy_number"] == "SQ-CASCO-204350")
    assert policy["status"] == "cancelled" and policy["refund_amount"] == 163800
    with pytest.raises(ActionError) as err:
        ex.run("cancel_policy", {"policy_number": "SQ-CASCO-204350", "cancel_reason": "снова"}, data)
    assert err.value.code == "already_done"


def test_cancel_policy_with_paid_claim_not_eligible(ex, data):
    with pytest.raises(ActionError) as err:
        ex.run("cancel_policy", {"policy_number": "SQ-CASCO-204118", "cancel_reason": "x"}, data)
    assert err.value.code == "not_eligible"


def test_create_policy_number_and_record(ex, data, catalog):
    before = len(data["policies"])
    out = ex.run("create_policy", {"product_type": "ogpo", "phone": "+77010000001", "price": 38000}, data)
    assert re.match(catalog.slots["policy_number"]["pattern"], out["policy_number"])
    assert out["policy_number"] == "SQ-OGPO-105121"
    assert out["payment_link_sent_to"] == "+77010000001"
    assert len(data["policies"]) == before + 1
    added = data["policies"][-1]
    assert added["client_id"] == "C001" and added["status"] == "pending_payment" and added["premium"] == 38000
    assert added["start_date"] == "2026-10-01" and added["end_date"] == "2027-09-30"
    with pytest.raises(ActionError) as err:
        ex.run("create_policy", {"product_type": "ogpo", "phone": "12345"}, data)
    assert err.value.code == "invalid_input"


def test_find_client(ex, data):
    assert ex.run("find_client", {"phone": "+77010000002"}, data) == {"client_id": "C002", "full_name": "Aigerim Bekova"}
    assert ex.run("find_client", {"iin": "850314300121"}, data)["client_id"] == "C001"
    with pytest.raises(ActionError) as err:
        ex.run("find_client", {"phone": "+77010000099"}, data)
    assert err.value.code == "not_found"


def test_get_policy_by_number_and_plate(ex, data):
    out = ex.run("get_policy", {"policy_number": "SQ-OGPO-102850"}, data)
    assert out["status"] == "expired"
    assert ex.run("get_policy", {"vehicle_plate": "777ABC02"}, data)["status"] == "active"
    with pytest.raises(ActionError) as err:
        ex.run("get_policy", {"policy_number": "ABC"}, data)
    assert err.value.code == "invalid_input"


def test_claims_flow(ex, data):
    out = ex.run("create_claim", {"product_type": "ogpo", "incident_date": "2026-09-28",
                                  "incident_description": "ДТП", "culprit_vehicle_plate": "101AAA02"}, data)
    assert out["claim_number"] == "CL-500331"
    claim = ex.run("get_claim", {"claim_number": "CL-500331"}, data)
    assert claim["status"] == "registered" and claim["next_step"]
    assert ex.run("get_claim", {"client_id": "C007"}, data)["claim_number"] == "CL-500330"
    with pytest.raises(ActionError) as err:
        ex.run("create_claim", {"product_type": "casco", "incident_date": "2026-12-01",
                                "incident_description": "x", "policy_number": "SQ-CASCO-204300"}, data)
    assert err.value.code == "invalid_input"
    ticket = ex.run("create_dispute", {"claim_number": "CL-500287", "complaint_text": "мало"}, data)["ticket_id"]
    assert re.match(r"^T-\d{6}$", ticket) and data["tickets"][0]["type"] == "dispute"
    booking = ex.run("book_inspection", {"claim_number": "CL-500330", "city": "Astana", "preferred_date": "2026-10-03"}, data)
    assert booking == {"slot_datetime": "2026-10-03 10:00", "address": "Kabanbay Batyr Ave 80", "hours": "Mon-Sat 09:00-17:00"}


def test_dms_actions(ex, data):
    out = ex.run("book_appointment", {"policy_number": "SQ-DMS-604220", "doctor_specialty": "лор",
                                      "city": "Astana", "preferred_date": "2026-10-05"}, data)
    assert out["clinic_name"] == "Saulet Medical" and out["slot_datetime"] == "2026-10-05 09:30"
    assert ex.run("check_coverage", {"policy_number": "SQ-DMS-604220", "service_name": "МРТ"}, data)["covered"] is True
    assert ex.run("check_coverage", {"policy_number": "SQ-DMS-604220", "service_name": "имплант зуба"}, data)["covered"] is False
    with pytest.raises(ActionError) as err:
        ex.run("check_coverage", {"policy_number": "SQ-OGPO-104501", "service_name": "МРТ"}, data)
    assert err.value.code == "policy_inactive"
    assert len(ex.run("list_clinics", {"city": "Almaty", "doctor_specialty": "стоматолог"}, data)["clinics"]) == 1


def test_renew_update_and_misc(ex, data):
    renewed = ex.run("renew_policy", {"policy_number": "SQ-OGPO-102850"}, data)
    assert renewed["policy_number"] == "SQ-OGPO-105121" and renewed["price"] == 31200 and renewed["start_date"] == "2026-10-01"
    upd = ex.run("update_policy", {"policy_number": "SQ-OGPO-104777", "new_driver_iin": "890922300345"}, data)
    assert upd["extra_premium"] == 22800  # class 10 (0.6) -> class 1 (1.2)
    assert ex.run("update_policy", {"policy_number": "SQ-OGPO-104501", "vehicle_plate": "888ABC02"}, data)["extra_premium"] == 0
    assert ex.run("check_payment", {"client_id": "C003", "payment_date": "2026-10-01"}, data)["payment_status"] == "charged_policy_not_issued"
    assert ex.run("update_contact", {"client_id": "C001", "contact_field": "email", "new_value": "new@mail.example"}, data)["new_value"] == "new@mail.example"
    assert ex.run("get_offices", {"city": "almaty"}, data)["address"] == "Abai Ave 150"
    assert "casco" in ex.run("kb_lookup", {"topic": "payments.installments"}, data)["answer"]
    assert ex.run("kb_lookup", {"topic": "fraud_policy"}, data)["answer"]
    assert ex.run("transfer_to_operator", {"queue": "claims_team"}, data) == {"queue": "claims_team", "simulated": True}
    with pytest.raises(ValueError):
        ex.run("transfer_to_operator", {"queue": "nope"}, data)
    assert ex.run("resend_documents", {"policy_number": "SQ-PROP-404077"}, data)["sent_to"] == "natalia.s@mail.example"
    assert ex.run("request_document", {"policy_number": "SQ-TRVL-304552", "document_type": "embassy_certificate",
                                       "email": "a@b.kz"}, data)["delivery"].startswith("email")


def test_unknown_action(ex, data):
    with pytest.raises(ValueError):
        ex.run("launch_rocket", {}, data)
    with pytest.raises(ValueError):
        ex.is_irreversible("launch_rocket")


def test_all_actions_have_handlers_and_irreversible_matches(ex, catalog):
    for name, spec in catalog.actions.items():
        assert hasattr(ex, f"_a_{name}"), name
        assert ex.is_irreversible(name) == spec["irreversible"]


def test_error_codes_are_from_actions_json():
    source = (ROOT / "backend" / "executor.py").read_text(encoding="utf-8")
    allowed = set(json.loads((ROOT / "actions.json").read_text(encoding="utf-8"))["error_codes"])
    used = set(re.findall(r'ActionError\("([a-z_]+)"', source))
    assert used and used <= allowed
