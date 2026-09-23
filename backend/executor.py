"""Data-driven mock executor for the 31 actions of actions.json.

All reads and writes go to the ``data`` dict passed to ``run`` (a deepcopy of
mock_backend.json owned by the session). Facts come from knowledge_base.json via
the Catalog. Only stdlib; error codes are limited to actions.json error_codes.
"""
import json
import re
from datetime import date, timedelta

from .config import ROOT

DATE_FMT = "%Y-%m-%d"

POLICY_PREFIX = {"ogpo": "OGPO", "casco": "CASCO", "travel": "TRVL",
                 "property": "PROP", "accident": "NS", "dms": "DMS"}

ZONE_A = {"russia", "uzbekistan", "kyrgyzstan", "tajikistan", "belarus", "armenia", "azerbaijan",
          "moldova", "turkmenistan", "georgia", "россия", "ресей", "узбекистан", "өзбекстан",
          "грузия", "киргизия", "кыргызстан", "қырғызстан", "таджикистан", "беларусь", "белоруссия",
          "армения", "азербайджан", "молдова", "туркменистан"}
ZONE_B = {"germany", "france", "italy", "spain", "poland", "czech republic", "czechia", "austria",
          "netherlands", "belgium", "greece", "portugal", "finland", "sweden", "norway", "denmark",
          "switzerland", "hungary", "estonia", "latvia", "lithuania", "slovakia", "slovenia", "croatia",
          "iceland", "luxembourg", "malta", "liechtenstein", "united kingdom", "uk", "great britain",
          "england", "германия", "франция", "италия", "испания", "польша", "чехия", "австрия",
          "нидерланды", "голландия", "бельгия", "греция", "португалия", "финляндия", "швеция",
          "норвегия", "дания", "швейцария", "венгрия", "эстония", "латвия", "литва", "словакия",
          "словения", "хорватия", "исландия", "люксембург", "мальта", "великобритания", "англия"}
ZONE_D = {"usa", "united states", "united states of america", "us", "canada", "сша", "америка",
          "ақш", "канада"}

SPECIALTY_ALIASES = {
    "терапевт": "therapist", "лор": "ENT", "отоларинголог": "ENT", "стоматолог": "dentist",
    "зубной": "dentist", "кардиолог": "cardiologist", "гинеколог": "gynecologist",
    "педиатр": "pediatrician", "узи": "ultrasound", "анализы": "lab", "анализ": "lab",
    "лаборатория": "lab", "дәрігер": "therapist", "тіс дәрігері": "dentist",
}

COVERAGE_KEYWORDS = [
    (("lab", "анализ", "талдау"), ("lab",)),
    (("mri", "мрт"), ("mri",)),
    (("ct", "кт", "томограф"), ("ct",)),
    (("prosthet", "протез", "имплант"), ("prosthetics", "implants")),
    (("dent", "стомат", "зуб", "тіс"), ("dent",)),
    (("therapist", "терапевт"), ("therapist",)),
    (("ultrasound", "узи"), ("ultrasound",)),
    (("hospital", "госпитал", "стационар"), ("hospitalization",)),
    (("medication", "лекарств", "дәрі"), ("medication",)),
    (("cosmet", "космет"), ("cosmetology",)),
]


class ActionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _date(value, field="дата"):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ActionError("invalid_input", f"Неверный формат: {field}")


def _int(value, field):
    try:
        return int(str(value).replace(" ", ""))
    except (TypeError, ValueError):
        raise ActionError("invalid_input", f"Неверное число: {field}")


def _next_number(existing, prefix, width=6, start=100000):
    nums = [int(m.group(1)) for m in (re.match(rf"^{re.escape(prefix)}(\d+)$", str(e)) for e in existing) if m]
    return f"{prefix}{(max(nums) + 1 if nums else start):0{width}d}"


class Executor:
    def __init__(self, catalog):
        self.catalog = catalog
        self.actions = catalog.actions
        self.kb = catalog.knowledge
        self.slots = catalog.slots
        self.as_of = date.fromisoformat(catalog.as_of_date)
        try:
            raw = json.loads((ROOT / "actions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        self.error_codes = set(raw.get("error_codes") or
                               ["not_found", "invalid_input", "policy_inactive", "not_eligible",
                                "not_covered", "no_availability", "already_done", "service_unavailable"])
        self.queues = list(raw.get("queues") or ["operator_general", "claims_team", "medical_assistance_24_7",
                                                  "corporate_sales", "complaints_team", "security_team"])

    # ---------- public API ----------
    def is_irreversible(self, name):
        if name not in self.actions:
            raise ValueError(f"Unknown action {name}")
        return bool(self.actions[name].get("irreversible"))

    def run(self, name, params, data):
        if name not in self.actions:
            raise ValueError(f"Unknown action {name}")
        handler = getattr(self, f"_a_{name}", None)
        if handler is None:
            raise ValueError(f"Action {name} has no handler")
        return handler(dict(params or {}), data)

    def policies_for(self, data, client_id, product=None):
        return [p for p in data.get("policies", [])
                if p.get("client_id") == client_id and (product is None or p.get("product") == product)]

    # ---------- helpers ----------
    def _pattern(self, slot):
        return self.slots.get(slot, {}).get("pattern")

    def _check(self, slot, value, label=None):
        pattern = self._pattern(slot)
        value = "" if value is None else str(value).strip()
        if pattern and not re.match(pattern, value):
            raise ActionError("invalid_input", f"Неверный формат: {label or slot}")
        return value

    def _client_by(self, data, **kw):
        for c in data.get("clients", []):
            if all(c.get(k) == v for k, v in kw.items()):
                return c
        return None

    def _client_or_404(self, data, client_id):
        client = self._client_by(data, client_id=client_id)
        if not client:
            raise ActionError("not_found", f"Клиент {client_id} не найден")
        return client

    def _policy(self, data, number):
        for p in data.get("policies", []):
            if p.get("policy_number") == number:
                return p
        return None

    def _policy_or_404(self, data, number):
        number = self._check("policy_number", number, "номер полиса")
        policy = self._policy(data, number)
        if not policy:
            raise ActionError("not_found", f"Полис {number} не найден")
        return policy

    def _status(self, policy, on=None):
        if policy.get("status") == "cancelled":
            return "cancelled"
        if policy.get("status") == "pending_payment":
            return "pending_payment"
        on = on or self.as_of
        start, end = _date(policy["start_date"]), _date(policy["end_date"])
        if on < start:
            return "not_started"
        if on > end:
            return "expired"
        return "active"

    def _claim(self, data, number):
        for c in data.get("claims", []):
            if c.get("claim_number") == number:
                return c
        return None

    def _bm_coef(self, cls):
        return float(self.kb["products"]["ogpo"]["pricing"]["bm_coef"][str(cls)])

    def _worst_class(self, classes):
        order = self.kb["bonus_malus"]["classes"]
        return min((str(c) for c in classes), key=lambda c: order.index(c) if c in order else len(order))

    def _client_class(self, data, iin):
        client = self._client_by(data, iin=iin)
        return str(client["bm_class"]) if client and client.get("bm_class") else str(data["defaults"]["unknown_iin_bm_class"])

    def _new_ticket(self, data, prefix, kind, payload):
        data.setdefault("tickets", [])
        ticket_id = _next_number([t.get("ticket_id") for t in data["tickets"]], prefix)
        ticket = {"ticket_id": ticket_id, "type": kind, "status": "registered", "created_at": self.as_of.isoformat()}
        ticket.update(payload)
        data["tickets"].append(ticket)
        return ticket_id

    def _kb_get(self, *path):
        node = self.kb
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    # ---------- clients / policies ----------
    def _a_find_client(self, p, data):
        phone, iin = p.get("phone"), p.get("iin")
        if not phone and not iin:
            raise ActionError("invalid_input", "Нужен телефон или ИИН")
        client = None
        if phone:
            client = self._client_by(data, phone=self._check("phone", phone, "телефон"))
        if not client and iin:
            client = self._client_by(data, iin=self._check("iin", iin, "ИИН"))
        if not client:
            raise ActionError("not_found", "Клиент по указанным данным не найден")
        return {"client_id": client["client_id"], "full_name": client["full_name"]}

    def _a_get_policies(self, p, data):
        client = self._client_or_404(data, p.get("client_id"))
        policies = [dict(pol, status=self._status(pol)) for pol in self.policies_for(data, client["client_id"])]
        return {"policies": policies}

    def _a_get_policy(self, p, data):
        number, plate = p.get("policy_number"), p.get("vehicle_plate")
        if not number and not plate:
            raise ActionError("invalid_input", "Нужен номер полиса или госномер")
        policy = None
        if number:
            policy = self._policy_or_404(data, number)
        else:
            plate = self._check("vehicle_plate", plate, "госномер")
            matches = [pol for pol in data.get("policies", []) if pol.get("details", {}).get("vehicle_plate") == plate]
            active = [pol for pol in matches if self._status(pol) == "active"]
            policy = (active or matches or [None])[0]
            if not policy:
                raise ActionError("not_found", f"Полис по госномеру {plate} не найден")
        return {"policy_number": policy["policy_number"], "product": policy["product"],
                "status": self._status(policy), "end_date": policy["end_date"],
                "client_id": policy.get("client_id"), "start_date": policy["start_date"],
                "premium": policy.get("premium"), "details": policy.get("details", {})}

    def _a_get_bm_class(self, p, data):
        iin = self._check("iin", p.get("iin"), "ИИН")
        return {"bm_class": self._client_class(data, iin)}

    # ---------- pricing ----------
    def _a_calc_ogpo_price(self, p, data):
        pricing = self.kb["products"]["ogpo"]["pricing"]
        region = str(p.get("region") or "other").lower()
        vehicle = str(p.get("vehicle_type") or "car").lower()
        if region not in pricing["base_by_region_kzt"]:
            raise ActionError("invalid_input", "Неизвестный регион")
        if vehicle not in pricing["vehicle_type_coef"]:
            raise ActionError("invalid_input", "Неизвестный тип транспорта")
        drivers = p.get("drivers_iin") or []
        if isinstance(drivers, str):
            drivers = [d for d in re.split(r"[,\s;]+", drivers) if d]
        drivers = [self._check("iin", d, "ИИН водителя") for d in drivers]
        classes = [self._client_class(data, d) for d in drivers] or [str(data["defaults"]["unknown_iin_bm_class"])]
        worst = self._worst_class(classes)
        term = str(p.get("term_months") or 12)
        if term not in pricing["term_coef"]:
            raise ActionError("invalid_input", "Недопустимый срок полиса")
        price = (pricing["base_by_region_kzt"][region] * pricing["vehicle_type_coef"][vehicle]
                 * self._bm_coef(worst) * pricing["term_coef"][term])
        return {"price": int(round(price)), "bm_class": worst}

    def _a_calc_casco_price(self, p, data):
        pricing = self.kb["products"]["casco"]["pricing"]
        value, year = _int(p.get("car_value"), "стоимость авто"), _int(p.get("car_year"), "год выпуска")
        franchise = str(_int(p.get("franchise") or 0, "франшиза"))
        package = str(p.get("package") or "Standard")
        if package not in pricing["package_coef"]:
            raise ActionError("invalid_input", "Неизвестный пакет КАСКО")
        if franchise not in pricing["franchise_coef"]:
            raise ActionError("invalid_input", "Недопустимая франшиза")
        if value <= 0:
            raise ActionError("invalid_input", "Стоимость авто должна быть больше нуля")
        age = self.as_of.year - year
        if age < 0:
            raise ActionError("invalid_input", "Год выпуска в будущем")
        if age > pricing["max_car_age"][package]:
            raise ActionError("not_eligible", f"Авто старше {pricing['max_car_age'][package]} лет не страхуется по пакету {package}")
        rate = None
        for rng, r in pricing["rate_by_car_age"].items():
            lo, hi = (int(x) for x in rng.split("-"))
            if lo <= age <= hi:
                rate = r
                break
        if rate is None:
            rate = max(pricing["rate_by_car_age"].values())
        price = value * rate * pricing["franchise_coef"][franchise] * pricing["package_coef"][package]
        return {"price": int(round(price)), "car_age": age, "package": package}

    @staticmethod
    def _zone(country):
        c = str(country or "").strip().lower()
        if c in ZONE_A:
            return "A"
        if c in ZONE_B:
            return "B"
        if c in ZONE_D:
            return "D"
        return "C"

    def _a_calc_travel_price(self, p, data):
        travel = self.kb["products"]["travel"]
        start, end = _date(p.get("trip_start"), "начало поездки"), _date(p.get("trip_end"), "конец поездки")
        if end < start:
            raise ActionError("invalid_input", "Дата окончания раньше даты начала")
        if start < self.as_of:
            raise ActionError("invalid_input", "Поездка не может начинаться в прошлом")
        travelers = _int(p.get("travelers_count") or 1, "число путешественников")
        age = _int(p.get("traveler_max_age") or 0, "возраст")
        if travelers <= 0 or age < 0:
            raise ActionError("invalid_input", "Проверьте число путешественников и возраст")
        if age > 75:
            raise ActionError("not_eligible", "Путешественники старше 75 лет — только через оператора")
        age_coef = 2.0 if age >= 65 else 1.0
        zone = self._zone(p.get("trip_country"))
        info = travel["zones"][zone]
        days = (end - start).days + 1
        price = info["rate_per_day_kzt"] * days * travelers * age_coef
        return {"price": int(round(price)), "zone": zone, "coverage": info["coverage"], "days": days}

    def _price_table(self, product, sum_insured):
        table = self.kb["products"][product]["price_per_year_kzt"]
        key = str(_int(sum_insured, "страховая сумма"))
        if key not in table:
            raise ActionError("invalid_input", f"Доступные суммы: {', '.join(table)}")
        return table[key]

    def _a_calc_property_price(self, p, data):
        ptype = str(p.get("property_type") or "apartment").lower()
        if ptype not in ("apartment", "house"):
            raise ActionError("invalid_input", "Тип недвижимости: apartment или house")
        price = self._price_table("property", p.get("sum_insured"))
        if ptype == "house":
            price *= self.kb["products"]["property"]["house_coef"]
        return {"price": int(round(price))}

    def _a_calc_accident_price(self, p, data):
        return {"price": int(self._price_table("accident", p.get("sum_insured")))}

    # ---------- policy lifecycle ----------
    @staticmethod
    def _year_end(start):
        try:
            return date(start.year + 1, start.month, start.day) - timedelta(days=1)
        except ValueError:  # 29 Feb
            return date(start.year + 1, 2, 28)

    def _a_create_policy(self, p, data):
        product = str(p.get("product_type") or "").lower()
        if product not in POLICY_PREFIX:
            raise ActionError("invalid_input", "Неизвестный продукт")
        phone = self._check("phone", p.get("phone"), "телефон")
        client = self._client_by(data, phone=phone)
        details = dict(p.get("details") or {})
        start = self.as_of
        end = self._year_end(start)
        if product == "travel" and details.get("trip_start") and details.get("trip_end"):
            start, end = _date(details["trip_start"]), _date(details["trip_end"])
        prefix = f"SQ-{POLICY_PREFIX[product]}-"
        number = _next_number([pol["policy_number"] for pol in data.get("policies", [])], prefix)
        price = p.get("price")
        policy = {"policy_number": number, "client_id": client["client_id"] if client else None,
                  "product": product, "start_date": start.isoformat(), "end_date": end.isoformat(),
                  "premium": int(price) if price is not None else None, "details": details,
                  "status": "pending_payment", "phone": phone}
        data.setdefault("policies", []).append(policy)
        return {"policy_number": number, "payment_link_sent_to": phone, "price": policy["premium"]}

    def _a_renew_policy(self, p, data):
        old = self._policy_or_404(data, p.get("policy_number"))
        if old.get("status") == "cancelled":
            raise ActionError("not_eligible", "Расторгнутый полис нельзя продлить")
        old_end = _date(old["end_date"])
        start = old_end + timedelta(days=1) if old_end >= self.as_of else self.as_of
        end = self._year_end(start)
        prefix = f"SQ-{POLICY_PREFIX[old['product']]}-"
        number = _next_number([pol["policy_number"] for pol in data.get("policies", [])], prefix)
        policy = {"policy_number": number, "client_id": old.get("client_id"), "product": old["product"],
                  "start_date": start.isoformat(), "end_date": end.isoformat(), "premium": old.get("premium"),
                  "details": dict(old.get("details") or {}), "status": "pending_payment", "renewed_from": old["policy_number"]}
        data["policies"].append(policy)
        return {"policy_number": number, "price": old.get("premium"), "start_date": policy["start_date"], "end_date": policy["end_date"]}

    def _a_update_policy(self, p, data):
        policy = self._policy_or_404(data, p.get("policy_number"))
        if self._status(policy) != "active":
            raise ActionError("policy_inactive", "Полис не действует, изменения невозможны")
        details = policy.setdefault("details", {})
        extra = 0
        changed = []
        if p.get("new_driver_iin"):
            iin = self._check("iin", p["new_driver_iin"], "ИИН водителя")
            drivers = details.setdefault("drivers_iin", [])
            current_worst = self._worst_class([self._client_class(data, d) for d in drivers] or ["3"])
            new_cls = self._client_class(data, iin)
            premium = policy.get("premium") or 0
            extra = max(0, int(round(premium * self._bm_coef(new_cls) / self._bm_coef(current_worst) - premium)))
            if iin not in drivers:
                drivers.append(iin)
            if extra:
                policy["premium"] = premium + extra
            changed.append("driver")
        if p.get("vehicle_plate"):
            details["vehicle_plate"] = self._check("vehicle_plate", p["vehicle_plate"], "госномер")
            changed.append("vehicle_plate")
        if not changed:
            raise ActionError("invalid_input", "Укажите ИИН нового водителя или новый госномер")
        return {"extra_premium": extra, "changed": changed}

    @staticmethod
    def _unused_full_months(start, end):
        e = end + timedelta(days=1)
        months = (e.year - start.year) * 12 + (e.month - start.month)
        if e.day < start.day:
            months -= 1
        return max(0, months)

    def _a_cancel_policy(self, p, data):
        policy = self._policy_or_404(data, p.get("policy_number"))
        if policy.get("status") == "cancelled":
            raise ActionError("already_done", "Полис уже расторгнут")
        if self._status(policy) != "active":
            raise ActionError("policy_inactive", "Полис не действует, расторжение невозможно")
        if any(c.get("policy_number") == policy["policy_number"] and c.get("status") == "paid" for c in data.get("claims", [])):
            raise ActionError("not_eligible", "По полису была выплата — возврат не предусмотрен")
        months = self._unused_full_months(self.as_of, _date(policy["end_date"]))
        refund = int(round((policy.get("premium") or 0) * months / 12 * 0.9))
        policy["status"] = "cancelled"
        policy["cancelled_at"] = self.as_of.isoformat()
        policy["cancel_reason"] = p.get("cancel_reason")
        policy["refund_amount"] = refund
        return {"refund_amount": refund, "unused_full_months": months}

    # ---------- claims ----------
    def _a_create_claim(self, p, data):
        product = str(p.get("product_type") or "").lower()
        incident = _date(p.get("incident_date"), "дата события")
        if incident > self.as_of:
            raise ActionError("invalid_input", "Дата события в будущем")
        policy, claim_type = None, product
        if p.get("policy_number"):
            policy = self._policy_or_404(data, p["policy_number"])
        elif p.get("culprit_vehicle_plate"):
            plate = self._check("vehicle_plate", p["culprit_vehicle_plate"], "госномер виновника")
            for pol in data.get("policies", []):
                if pol.get("product") == "ogpo" and pol.get("details", {}).get("vehicle_plate") == plate:
                    policy = pol
                    break
            claim_type = "ogpo_victim"
            if not policy:
                raise ActionError("not_found", f"Полис ОГПО виновника с номером {plate} не найден")
        elif p.get("client_id"):
            self._client_or_404(data, p["client_id"])
            candidates = self.policies_for(data, p["client_id"], product or None)
            active = [c for c in candidates if self._status(c, incident) == "active"]
            policy = (active or candidates or [None])[0]
        if not policy:
            raise ActionError("not_found", "Полис для заявления не найден")
        if self._status(policy, incident) != "active":
            raise ActionError("policy_inactive", "Полис не действовал на дату события")
        number = _next_number([c["claim_number"] for c in data.get("claims", [])], "CL-", start=500000)
        claim = {"claim_number": number, "client_id": p.get("client_id") or policy.get("client_id"),
                 "policy_number": policy["policy_number"], "claim_type": claim_type or policy["product"],
                 "incident_date": incident.isoformat(), "description": p.get("incident_description"),
                 "status": "registered", "registered_at": self.as_of.isoformat(),
                 "next_step": f"Отправьте документы; решение — {self.kb['claims']['decision_time']}"}
        if p.get("culprit_vehicle_plate"):
            claim["culprit_vehicle_plate"] = p["culprit_vehicle_plate"]
        data.setdefault("claims", []).append(claim)
        return {"claim_number": number, "next_step": claim["next_step"], "policy_number": policy["policy_number"]}

    def _a_get_claim(self, p, data):
        claim = None
        if p.get("claim_number"):
            number = self._check("claim_number", p["claim_number"], "номер заявления")
            claim = self._claim(data, number)
            if not claim:
                raise ActionError("not_found", f"Заявление {number} не найдено")
        elif p.get("client_id"):
            claims = [c for c in data.get("claims", []) if c.get("client_id") == p["client_id"]]
            if not claims:
                raise ActionError("not_found", "Заявлений у клиента не найдено")
            claim = max(claims, key=lambda c: c.get("incident_date") or "")
        else:
            raise ActionError("not_found", "Нужен номер заявления или клиент")
        result = dict(claim)
        result.setdefault("next_step", "")
        return result

    def _a_create_dispute(self, p, data):
        number = self._check("claim_number", p.get("claim_number"), "номер заявления")
        claim = self._claim(data, number)
        if not claim:
            raise ActionError("not_found", f"Заявление {number} не найдено")
        ticket_id = self._new_ticket(data, "T-", "dispute", {"claim_number": number, "text": p.get("complaint_text"),
                                                              "client_id": claim.get("client_id"),
                                                              "review_time": self.kb["claims"]["dispute"]})
        return {"ticket_id": ticket_id, "review_time": self.kb["claims"]["dispute"]}

    def _a_book_inspection(self, p, data):
        number = self._check("claim_number", p.get("claim_number"), "номер заявления")
        claim = self._claim(data, number)
        if not claim:
            raise ActionError("not_found", f"Заявление {number} не найдено")
        city = str(p.get("city") or "").strip()
        points = {pt["city"].lower(): pt for pt in self.kb["inspection_points"]}
        point = points.get(city.lower()) or points["other"]
        preferred = _date(p.get("preferred_date"), "дата осмотра")
        if preferred < self.as_of:
            alternatives = ", ".join((self.as_of + timedelta(days=d)).isoformat() for d in (1, 2))
            raise ActionError("no_availability", f"Дата уже прошла. Ближайшие варианты: {alternatives}")
        slot = f"{preferred.isoformat()} 10:00"
        data.setdefault("bookings", []).append({"type": "inspection", "claim_number": number, "city": city,
                                                "slot_datetime": slot, "address": point["address"]})
        return {"slot_datetime": slot, "address": point["address"], "hours": point["hours"]}

    # ---------- DMS ----------
    @staticmethod
    def _normalize_specialty(value):
        v = str(value or "").strip().lower()
        for alias, canon in SPECIALTY_ALIASES.items():
            if alias in v:
                return canon
        return v

    def _clinics(self, city, specialty=None):
        canon = self._normalize_specialty(specialty).lower() if specialty else None
        result = []
        for clinic in self.kb["clinics"]:
            if clinic["city"].lower() != str(city or "").strip().lower():
                continue
            if canon and canon not in [s.lower() for s in clinic["specialties"]]:
                continue
            result.append(clinic)
        return result

    def _dms_policy(self, data, number):
        policy = self._policy_or_404(data, number)
        if policy.get("product") != "dms" or self._status(policy) != "active":
            raise ActionError("policy_inactive", "Действующий полис ДМС не найден")
        return policy

    def _a_book_appointment(self, p, data):
        policy = self._dms_policy(data, p.get("policy_number"))
        specialty = self._normalize_specialty(p.get("doctor_specialty"))
        if specialty == "dentist" and policy.get("details", {}).get("package") != "Comfort":
            raise ActionError("not_covered", "Стоматология не входит в пакет Basic")
        clinics = self._clinics(p.get("city"), specialty)
        if not clinics:
            raise ActionError("no_availability", f"В городе {p.get('city')} нет клиники с нужным специалистом")
        preferred = _date(p.get("preferred_date"), "дата приёма")
        if preferred < self.as_of:
            raise ActionError("no_availability", f"Дата уже прошла. Ближайший вариант: {(self.as_of + timedelta(days=1)).isoformat()}")
        clinic = clinics[0]
        slot = f"{preferred.isoformat()} 09:30"
        data.setdefault("bookings", []).append({"type": "appointment", "policy_number": policy["policy_number"],
                                                "clinic_name": clinic["name"], "specialty": specialty,
                                                "slot_datetime": slot, "address": clinic["address"]})
        return {"clinic_name": clinic["name"], "slot_datetime": slot, "address": clinic["address"]}

    def _a_check_coverage(self, p, data):
        policy = self._dms_policy(data, p.get("policy_number"))
        package = policy.get("details", {}).get("package") or "Basic"
        rules = self.kb["products"]["dms"]["packages"].get(package)
        if not rules:
            raise ActionError("policy_inactive", "Пакет ДМС не определён")
        service = str(p.get("service_name") or "").lower()
        keys = []
        for aliases, canon in COVERAGE_KEYWORDS:
            if any(a in service for a in aliases):
                keys.extend(canon)
        if not keys:
            return {"covered": False, "note": "Услуга не распознана, уточните у оператора", "package": package}
        for item in rules["not_covered"]:
            if any(k in item.lower() for k in keys):
                return {"covered": False, "note": f"Пакет {package}: не покрывается — {item}", "package": package}
        for item in rules["covered"]:
            if any(k in item.lower() for k in keys):
                return {"covered": True, "note": f"Пакет {package}: покрывается — {item}", "package": package}
        return {"covered": False, "note": "Услуга не найдена в пакете, уточните у оператора", "package": package}

    def _a_list_clinics(self, p, data):
        clinics = self._clinics(p.get("city"), p.get("doctor_specialty"))
        if not clinics:
            raise ActionError("not_found", f"Клиники в городе {p.get('city')} не найдены")
        return {"clinics": [dict(c) for c in clinics]}

    def _a_get_offices(self, p, data):
        city = str(p.get("city") or "").strip().lower()
        for office in self.kb["offices"]:
            if office["city"].lower() == city:
                return {"address": office["address"], "hours": office["hours"], "city": office["city"],
                        "offices": [dict(office)]}
        raise ActionError("not_found", f"Офис в городе {p.get('city')} не найден")

    # ---------- documents / payments / contacts ----------
    def _a_resend_documents(self, p, data):
        policy = self._policy_or_404(data, p.get("policy_number"))
        if self._status(policy) != "active":
            raise ActionError("policy_inactive", "Полис не действует")
        client = self._client_by(data, client_id=policy.get("client_id"))
        if not client or not client.get("email"):
            raise ActionError("not_found", "Email клиента не найден")
        return {"sent_to": client["email"], "policy_number": policy["policy_number"]}

    def _a_request_document(self, p, data):
        policy = self._policy_or_404(data, p.get("policy_number"))
        doc_type = str(p.get("document_type") or "")
        available = self.kb["documents_available"]
        if doc_type not in available:
            raise ActionError("invalid_input", f"Доступные документы: {', '.join(available)}")
        email = self._check("email", p.get("email"), "email")
        return {"sent_to": email, "delivery": available[doc_type], "policy_number": policy["policy_number"]}

    def _a_check_payment(self, p, data):
        self._client_or_404(data, p.get("client_id"))
        target = _date(p.get("payment_date"), "дата платежа")
        best, best_diff = None, None
        for pay in data.get("payments", []):
            if pay.get("client_id") != p["client_id"]:
                continue
            diff = abs((_date(pay["date"]) - target).days)
            if diff <= 3 and (best_diff is None or diff < best_diff):
                best, best_diff = pay, diff
        if not best:
            raise ActionError("not_found", "Платёж на эту дату не найден")
        return {"payment_status": best["status"], "amount": best["amount"], "note": best.get("note", ""),
                "policy_number": best.get("policy_number"), "payment_id": best.get("payment_id"), "date": best["date"]}

    def _a_update_contact(self, p, data):
        client = self._client_or_404(data, p.get("client_id"))
        field = str(p.get("contact_field") or "").lower()
        value = str(p.get("new_value") or "").strip()
        if field not in ("phone", "email", "address"):
            raise ActionError("invalid_input", "Поле: phone, email или address")
        if field in ("phone", "email"):
            value = self._check(field, value, field)
        if not value:
            raise ActionError("invalid_input", "Новое значение пустое")
        client[field] = value
        return {"updated_field": field, "new_value": value, "client_id": client["client_id"]}

    # ---------- knowledge / misc ----------
    def _a_kb_lookup(self, p, data):
        topic = str(p.get("topic") or "").strip()
        if not topic:
            raise ActionError("not_found", "Тема не указана")
        node = self._kb_get(*topic.split(".")) if "." in topic else None
        if node is None:
            node = self.kb.get(topic)
        if node is None:
            node = self._kb_get("products", topic.lower())
        if node is None:
            needle = topic.lower()
            hits = {}
            for key, value in self.kb.items():
                if key == "meta":
                    continue
                text = f"{key} {value}".lower()
                if needle in text or any(w in text for w in needle.split() if len(w) > 3):
                    hits[key] = value
            node = hits or None
        if node is None:
            raise ActionError("not_found", f"В базе знаний нет темы «{topic}»")
        return {"topic": topic, "answer": node}

    def _a_send_sms(self, p, data):
        phone = self._check("phone", p.get("phone"), "телефон")
        data.setdefault("sms_log", []).append({"phone": phone, "text": p.get("text")})
        return {"sent_to": phone, "simulated": True}

    def _a_create_callback(self, p, data):
        phone = self._check("phone", p.get("phone"), "телефон")
        when = str(p.get("callback_time") or "").strip()
        if not when:
            raise ActionError("invalid_input", "Укажите удобное время звонка")
        data.setdefault("callbacks", []).append({"phone": phone, "callback_time": when})
        return {"scheduled": when, "phone": phone}

    def _a_create_complaint(self, p, data):
        ticket_id = self._new_ticket(data, "T-", "complaint", {"text": p.get("complaint_text"),
                                                                "review_time": self.kb["complaints"]["review_time"]})
        return {"ticket_id": ticket_id, "review_time": self.kb["complaints"]["review_time"]}

    def _a_report_fraud(self, p, data):
        ticket_id = self._new_ticket(data, "F-", "fraud", {"text": p.get("fraud_details")})
        return {"ticket_id": ticket_id, "advice": self.kb["fraud_policy"]}

    def _a_transfer_to_operator(self, p, data):
        queue = str(p.get("queue") or "operator_general")
        if queue not in self.queues:
            raise ValueError(f"Unknown queue {queue}")
        data.setdefault("transfers", []).append({"queue": queue, "summary": p.get("summary")})
        return {"queue": queue, "simulated": True}
