"""Test fixture: the seven-domain Enterprise Reference Benchmark (thesis section 3.3.2).

Generates one *raw* domain knowledge graph per domain (Retail, Logistics,
Healthcare, Energy, Finance, Smart Building, Supply Chain) plus the inter-KG
identity graph of 16 directed ``owl:sameAs`` assertions.

The raw graphs carry no QB4OLAP markup: Phase I (KG2MD) has to discover the
fact class, measures and hierarchies on its own. Values are deterministic so
the thesis' audit numbers are reproducible:

* Alice (``retail:cust_1001`` / ``finance:trader_Alice``): 15 sales totalling
  USD 1,499.70 and 10 trades totalling USD 52,620.00.
* Bob (``retail:cust_1002`` / ``finance:trader_Bob``): 15 sales totalling
  USD 1,499.70 and 10 trades totalling USD 50,737.50.
* 200 observations in total (30/25/25/30/30/30/30).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

EX = "http://example.org/"
TIME = Namespace(EX + "time/")
GEO = Namespace(EX + "geo/")
UNIT = URIRef(EX + "vocab#unit")  # annotation property: unit of measure of a datatype property
IDENTITY_GRAPH = URIRef(EX + "graphs/identities")

DOMAINS = {
    "retail": "Retail",
    "logistics": "Logistics",
    "healthcare": "Healthcare",
    "energy": "Energy",
    "finance": "Finance",
    "building": "Building",
    "supplychain": "SupplyChain",
}


def ns(domain: str) -> Namespace:
    return Namespace(f"{EX}{domain}#")


@dataclass
class Benchmark:
    """Raw domain KGs keyed by domain name, plus the identity graph."""

    graphs: dict[str, Graph] = field(default_factory=dict)
    namespaces: dict[str, str] = field(default_factory=dict)
    identity: Graph = field(default_factory=Graph)


def _money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _split_total(rng: random.Random, total: str, n: int) -> list[Decimal]:
    """n positive cent amounts that sum exactly to ``total``."""
    total_d = Decimal(total)
    weights = [rng.uniform(0.6, 1.4) for _ in range(n)]
    s = sum(weights)
    parts = [_money(total_d * Decimal(w / s)) for w in weights[:-1]]
    parts.append(total_d - sum(parts))
    return parts


class _Builder:
    """Small helper that writes a raw domain KG with TBox + ABox triples."""

    def __init__(self, domain: str):
        self.d = domain
        self.n = ns(domain)
        self.g = Graph()
        self.g.bind(DOMAINS[domain].lower(), self.n)
        self.g.bind("time", TIME)
        self.g.bind("geo", GEO)
        self._calendar_done: set[URIRef] = set()

    def cls(self, name: str, label: str | None = None) -> URIRef:
        c = self.n[name]
        self.g.add((c, RDF.type, OWL.Class))
        self.g.add((c, RDFS.label, Literal(label or name)))
        return c

    def obj_prop(self, name: str, domain: URIRef, rng: URIRef) -> URIRef:
        p = self.n[name]
        self.g.add((p, RDF.type, OWL.ObjectProperty))
        self.g.add((p, RDFS.domain, domain))
        self.g.add((p, RDFS.range, rng))
        return p

    def data_prop(self, name: str, domain: URIRef, dt: URIRef, unit: str | None = None) -> URIRef:
        p = self.n[name]
        self.g.add((p, RDF.type, OWL.DatatypeProperty))
        self.g.add((p, RDFS.domain, domain))
        self.g.add((p, RDFS.range, dt))
        if unit:
            self.g.add((p, UNIT, Literal(unit)))
        return p

    def inst(self, local: str, cls: URIRef, label: str | None = None) -> URIRef:
        i = self.n[local]
        self.g.add((i, RDF.type, cls))
        if label:
            self.g.add((i, RDFS.label, Literal(label)))
        return i

    # Conformed calendar dimension: shared IRIs across all domains (Day -> Month -> Year
    # and Day -> Quarter -> Year: an *alternative* hierarchy).
    def calendar(self):
        day = self.cls("Day")
        month = self.cls("Month")
        quarter = self.cls("Quarter")
        year = self.cls("Year")
        return (
            day,
            self.obj_prop("inMonth", day, month),
            self.obj_prop("inQuarter", day, quarter),
            self.obj_prop("monthInYear", month, year),
            self.obj_prop("quarterInYear", quarter, year),
            (month, quarter, year),
        )

    def day(self, d: date, cal) -> URIRef:
        day_cls, in_month, in_quarter, m_in_y, q_in_y, (month_cls, quarter_cls, year_cls) = cal
        iri = TIME[f"day/{d.isoformat()}"]
        if iri in self._calendar_done:
            return iri
        self._calendar_done.add(iri)
        q = (d.month - 1) // 3 + 1
        m_iri = TIME[f"month/{d.year}-{d.month:02d}"]
        q_iri = TIME[f"quarter/{d.year}-Q{q}"]
        y_iri = TIME[f"year/{d.year}"]
        g = self.g
        g.add((iri, RDF.type, day_cls))
        g.add((iri, RDFS.label, Literal(d.isoformat())))
        g.add((iri, in_month, m_iri))
        g.add((iri, in_quarter, q_iri))
        g.add((m_iri, RDF.type, month_cls))
        g.add((m_iri, RDFS.label, Literal(f"{d.year}-{d.month:02d}")))
        g.add((m_iri, m_in_y, y_iri))
        g.add((q_iri, RDF.type, quarter_cls))
        g.add((q_iri, RDFS.label, Literal(f"{d.year}-Q{q}")))
        g.add((q_iri, q_in_y, y_iri))
        g.add((y_iri, RDF.type, year_cls))
        g.add((y_iri, RDFS.label, Literal(str(d.year))))
        return iri

    # Geography: City -> State -> Country, with a ragged skip City -> Country.
    def geography(self):
        city = self.cls("City")
        state = self.cls("State")
        country = self.cls("Country")
        return (
            city,
            self.obj_prop("cityInState", city, state),
            self.obj_prop("stateInCountry", state, country),
            self.obj_prop("cityInCountry", city, country),
            (state, country),
        )

    def place(self, city_name: str, geo) -> URIRef:
        city_cls, in_state, in_country, city_country, (state_cls, country_cls) = geo
        table = {
            "Berlin": (None, "Germany"),  # city-state: ragged skip
            "Munich": ("Bavaria", "Germany"),
            "Hamburg": (None, "Germany"),
            "Paris": ("Ile-de-France", "France"),
            "Lyon": ("Auvergne-Rhone-Alpes", "France"),
            "Austin": ("Texas", "USA"),
            "Seattle": ("Washington", "USA"),
            "Chittagong": ("Chattogram Division", "Bangladesh"),
        }
        state, country = table[city_name]
        c_iri = GEO[f"city/{city_name}"]
        k_iri = GEO[f"country/{country}"]
        g = self.g
        g.add((c_iri, RDF.type, city_cls))
        g.add((c_iri, RDFS.label, Literal(city_name)))
        g.add((k_iri, RDF.type, country_cls))
        g.add((k_iri, RDFS.label, Literal(country)))
        if state:
            s_iri = GEO[f"state/{state.replace(' ', '_')}"]
            g.add((s_iri, RDF.type, state_cls))
            g.add((s_iri, RDFS.label, Literal(state)))
            g.add((c_iri, in_state, s_iri))
            g.add((s_iri, in_country, k_iri))
        else:
            g.add((c_iri, city_country, k_iri))
        return c_iri


BASE_DAY = date(2026, 1, 5)


def _days(rng: random.Random, n: int) -> list[date]:
    return [BASE_DAY + timedelta(days=rng.randrange(0, 180)) for _ in range(n)]


def _retail(rng: random.Random) -> Graph:
    b = _Builder("retail")
    cal = b.calendar()
    geo = b.geography()
    sale = b.cls("SaleTransaction", "Sale Transaction")
    customer, product, category, store, distributor = (
        b.cls("Customer"), b.cls("Product"), b.cls("Category"), b.cls("Store"), b.cls("Distributor"))
    p_customer = b.obj_prop("customer", sale, customer)
    p_product = b.obj_prop("product", sale, product)
    p_store = b.obj_prop("store", sale, store)
    p_date = b.obj_prop("date", sale, cal[0])
    p_cat = b.obj_prop("productCategory", product, category)
    p_dist = b.obj_prop("productDistributor", product, distributor)  # parallel hierarchy
    p_store_city = b.obj_prop("storeCity", store, geo[0])
    p_cust_city = b.obj_prop("customerCity", customer, geo[0])
    p_email = b.data_prop("email", customer, XSD.string)
    m_amount = b.data_prop("saleTotalAmount", sale, XSD.decimal, "USD")
    m_qty = b.data_prop("quantitySold", sale, XSD.integer, "count")
    m_price = b.data_prop("unitPrice", sale, XSD.decimal, "USD")
    m_disc = b.data_prop("discount", sale, XSD.decimal, "ratio")

    cats = {c: b.inst(f"cat_{c}", category, c) for c in ("Beverages", "Electronics", "Apparel")}
    dists = {d: b.inst(f"dist_{d}", distributor, d) for d in ("NordTrade", "EuroLink")}
    products = []
    for i, (name, cat, dist) in enumerate([
        ("Espresso Beans", "Beverages", "NordTrade"), ("Green Tea", "Beverages", "EuroLink"),
        ("USB-C Hub", "Electronics", "EuroLink"), ("Headphones", "Electronics", "NordTrade"),
        ("Rain Jacket", "Apparel", "NordTrade"), ("Wool Scarf", "Apparel", "EuroLink"),
    ]):
        p = b.inst(f"prod_{i + 1}", product, name)
        b.g.add((p, p_cat, cats[cat]))
        b.g.add((p, p_dist, dists[dist]))
        products.append(p)
    stores = []
    for i, city in enumerate(("Berlin", "Munich", "Paris")):
        s = b.inst(f"store_{i + 1}", store, f"Store {city}")
        b.g.add((s, p_store_city, b.place(city, geo)))
        stores.append(s)
    people = {
        "cust_1001": ("Alice Johnson", "alice.johnson@example.com", "Berlin"),
        "cust_1002": ("Bob Smith", "bob.smith@example.com", "Paris"),
    }
    custs = {}
    for local, (label, email, city) in people.items():
        c = b.inst(local, customer, label)
        b.g.add((c, p_email, Literal(email)))
        b.g.add((c, p_cust_city, b.place(city, geo)))
        custs[local] = c

    n = 0
    for local, total in (("cust_1001", "1499.70"), ("cust_1002", "1499.70")):
        amounts = _split_total(rng, total, 15)
        for amt, d in zip(amounts, _days(rng, 15)):
            n += 1
            qty = rng.randint(1, 5)
            disc = _money(rng.choice([0, 0.05, 0.1, 0.15]))
            obs = b.inst(f"sale_{n:03d}", sale)
            g = b.g
            g.add((obs, p_customer, custs[local]))
            g.add((obs, p_product, rng.choice(products)))
            g.add((obs, p_store, rng.choice(stores)))
            g.add((obs, p_date, b.day(d, cal)))
            g.add((obs, m_amount, Literal(amt, datatype=XSD.decimal)))
            g.add((obs, m_qty, Literal(qty, datatype=XSD.integer)))
            g.add((obs, m_price, Literal(_money(amt / qty), datatype=XSD.decimal)))
            g.add((obs, m_disc, Literal(disc, datatype=XSD.decimal)))
    return b.g


def _finance(rng: random.Random) -> Graph:
    b = _Builder("finance")
    cal = b.calendar()
    trade = b.cls("InvestmentTrade", "Investment Trade")
    trader, security, sector, broker = b.cls("Trader"), b.cls("Security"), b.cls("Sector"), b.cls("Broker")
    p_trader = b.obj_prop("trader", trade, trader)
    p_sec = b.obj_prop("security", trade, security)
    p_date = b.obj_prop("tradeDate", trade, cal[0])
    p_sector = b.obj_prop("securitySector", security, sector)
    p_broker = b.obj_prop("trader_broker", trader, broker)
    p_reports = b.obj_prop("reportsTo", broker, broker)  # recursive hierarchy
    p_email = b.data_prop("contactEmail", trader, XSD.string)
    m_amount = b.data_prop("tradeAmount", trade, XSD.decimal, "USD")
    m_shares = b.data_prop("shareCount", trade, XSD.integer, "count")
    m_fee = b.data_prop("feePaid", trade, XSD.decimal, "USD")

    sectors = {s: b.inst(f"sector_{s}", sector, s) for s in ("Technology", "Energy", "Healthcare")}
    secs = []
    for i, (tick, s) in enumerate([("TCH", "Technology"), ("NRG", "Energy"), ("MED", "Healthcare"), ("CLD", "Technology")]):
        x = b.inst(f"sec_{tick}", security, tick)
        b.g.add((x, p_sector, sectors[s]))
        secs.append(x)
    head = b.inst("broker_head", broker, "Head of Desk")
    brokers = [head]
    for i in range(2):
        br = b.inst(f"broker_{i + 1}", broker, f"Broker {i + 1}")
        b.g.add((br, p_reports, head))
        brokers.append(br)
    traders = {}
    for local, label, email in (
        ("trader_Alice", "Alice Johnson", "alice.johnson@example.com"),
        ("trader_Bob", "Bob Smith", "bob.smith@example.com"),
        ("trader_Carol", "Carol Diaz", "carol.diaz@example.com"),
    ):
        t = b.inst(local, trader, label)
        b.g.add((t, p_email, Literal(email)))
        b.g.add((t, p_broker, rng.choice(brokers[1:])))
        traders[local] = t
    n = 0
    for local, total in (("trader_Alice", "52620.00"), ("trader_Bob", "50737.50"), ("trader_Carol", "41000.00")):
        for amt, d in zip(_split_total(rng, total, 10), _days(rng, 10)):
            n += 1
            o = b.inst(f"trade_{n:03d}", trade)
            g = b.g
            g.add((o, p_trader, traders[local]))
            g.add((o, p_sec, rng.choice(secs)))
            g.add((o, p_date, b.day(d, cal)))
            g.add((o, m_amount, Literal(amt, datatype=XSD.decimal)))
            g.add((o, m_shares, Literal(rng.randint(10, 400), datatype=XSD.integer)))
            g.add((o, m_fee, Literal(_money(amt * Decimal("0.002")), datatype=XSD.decimal)))
    return b.g


def _generic(rng, domain, fact, fact_label, dims, measures, n_obs, entities, extra=None):
    """Generic domain: one fact class with dimension links and numeric measures.

    dims: list of (prop, class, [(local, label)], parent) where parent is
    (prop, class, mapping local->(parent_local, parent_label)) or None.
    measures: list of (prop, xsd, unit, sampler).
    """
    b = _Builder(domain)
    cal = b.calendar()
    geo = b.geography()
    f = b.cls(fact, fact_label)
    p_date = b.obj_prop(entities.get("date_prop", "date"), f, cal[0])
    dim_members = []
    for prop, cname, members, parent in dims:
        c = b.cls(cname)
        p = b.obj_prop(prop, f, c)
        insts = []
        par_cls = par_prop = None
        if parent:
            par_prop_name, par_cname, mapping = parent
            par_cls = b.cls(par_cname)
            par_prop = b.obj_prop(par_prop_name, c, par_cls)
        for local, label in members:
            i = b.inst(local, c, label)
            if parent:
                for plocal, plabel in mapping[local] if isinstance(mapping[local], list) else [mapping[local]]:
                    if plocal.startswith("city:"):
                        b.g.add((i, par_prop, b.place(plocal[5:], geo)))
                    else:
                        b.g.add((i, par_prop, b.inst(plocal, par_cls, plabel)))
            insts.append(i)
        dim_members.append((p, insts))
    mprops = [(b.data_prop(name, f, dt, unit), dt, sampler) for name, dt, unit, sampler in measures]
    if extra:
        extra(b)
    for k, d in enumerate(_days(rng, n_obs)):
        o = b.inst(f"{fact.lower()}_{k + 1:03d}", f)
        b.g.add((o, p_date, b.day(d, cal)))
        for p, insts in dim_members:
            b.g.add((o, p, insts[k % len(insts)] if k < len(insts) else rng.choice(insts)))
        for p, dt, sampler in mprops:
            b.g.add((o, p, Literal(sampler(rng), datatype=dt)))
    return b.g


def _r(lo, hi, nd=2):
    return lambda rng: _money(round(rng.uniform(lo, hi), nd)) if nd == 2 else round(rng.uniform(lo, hi), nd)


def _i(lo, hi):
    return lambda rng: rng.randint(lo, hi)


def build_enterprise_benchmark(seed: int = 7) -> Benchmark:
    rng = random.Random(seed)
    bm = Benchmark()
    bm.graphs["retail"] = _retail(rng)
    bm.graphs["finance"] = _finance(rng)
    bm.graphs["logistics"] = _generic(
        rng, "logistics", "SupplierPurchaseOrder", "Supplier Purchase Order",
        [
            ("supplier", "Supplier", [("supplier_Bob", "Bob Smith"), ("supplier_Acme", "Acme Freight Ltd"),
                                      ("supplier_Orion", "Orion Components")],
             ("supplierCity", "City", {"supplier_Bob": ("city:Paris", None), "supplier_Acme": ("city:Hamburg", None),
                                       "supplier_Orion": ("city:Austin", None)})),
            ("warehouse", "Warehouse", [("wh_north", "North Hub"), ("wh_south", "South Hub")],
             # nonstrict: a warehouse serves several regions
             ("servesRegion", "Region", {"wh_north": [("region_EU", "EU"), ("region_UK", "UK")],
                                         "wh_south": [("region_EU", "EU")]})),
        ],
        [("freightCost", XSD.decimal, "USD", _r(80, 900)), ("orderQuantity", XSD.integer, "count", _i(5, 500)),
         ("leadTimeDays", XSD.decimal, "days", _r(1, 30))],
        25, {"date_prop": "orderDate"},
    )
    bm.graphs["healthcare"] = _generic(
        rng, "healthcare", "DiagnosticLabTest", "Diagnostic Lab Test",
        [
            ("lab", "Lab", [("lab_Central", "Central Medical Campus"), ("lab_East", "East Clinic Lab")],
             ("labCity", "City", {"lab_Central": ("city:Seattle", None), "lab_East": ("city:Austin", None)})),
            ("testType", "TestType", [("tt_cbc", "Complete Blood Count"), ("tt_lipid", "Lipid Panel"), ("tt_a1c", "HbA1c")],
             ("testCategory", "TestCategory", {"tt_cbc": ("tc_hem", "Hematology"), "tt_lipid": ("tc_chem", "Chemistry"),
                                               "tt_a1c": ("tc_chem", "Chemistry")})),
        ],
        [("turnaroundHours", XSD.decimal, "hours", _r(2, 72)), ("testCost", XSD.decimal, "USD", _r(15, 250)),
         ("resultScoreRatio", XSD.decimal, "ratio", lambda r: _money(r.uniform(0, 1)))],
        25, {"date_prop": "testDate"},
    )
    bm.graphs["energy"] = _generic(
        rng, "energy", "MeterReading", "Meter Reading",
        [
            ("meter", "Meter", [("meter_1", "Meter 1"), ("meter_2", "Meter 2"), ("meter_3", "Meter 3")],
             ("meterSite", "Site", {"meter_1": ("site_Acme", "Acme Freight Ltd"), "meter_2": ("site_Central", "Central Medical Campus"),
                                    "meter_3": ("site_Central", "Central Medical Campus")})),
        ],
        [("energyConsumedKwh", XSD.decimal, "kWh", _r(50, 900)), ("peakDemandKw", XSD.decimal, "kW", _r(5, 90)),
         ("voltageLevel", XSD.decimal, "V", _r(220, 240))],
        30, {"date_prop": "readingDate"},
    )
    bm.graphs["building"] = _generic(
        rng, "building", "SensorReading", "Sensor Reading",
        [
            ("sensor", "Sensor", [("sensor_a", "Sensor A"), ("sensor_b", "Sensor B"), ("sensor_c", "Sensor C")],
             ("sensorRoom", "Room", {"sensor_a": ("room_101", "Room 101"), "sensor_b": ("room_102", "Room 102"),
                                     "sensor_c": ("room_201", "Room 201")})),
            ("building", "BuildingSite", [("building_Central", "Central Medical Campus"), ("building_HQ", "Head Office")], None),
        ],
        [("temperatureCelsius", XSD.decimal, "celsius", _r(18, 27)), ("humidityPct", XSD.decimal, "percent", _r(30, 60)),
         ("occupancyCount", XSD.integer, "count", _i(0, 40))],
        30, {"date_prop": "readingDate"},
    )
    bm.graphs["supplychain"] = _generic(
        rng, "supplychain", "FreightShipment", "Freight Shipment",
        [
            ("carrier", "Carrier", [("carrier_Acme", "Acme Freight Ltd"), ("carrier_Swift", "Swift Lines")], None),
            ("consignee", "Consignee", [("consignee_Alice", "Alice Johnson"), ("consignee_Zed", "Zed Retail Group")],
             ("consigneeCity", "City", {"consignee_Alice": ("city:Berlin", None), "consignee_Zed": ("city:Lyon", None)})),
        ],
        [("shipmentWeightKg", XSD.decimal, "kg", _r(100, 5000)), ("freightCharge", XSD.decimal, "USD", _r(200, 4000)),
         ("transitDays", XSD.decimal, "days", _r(1, 20))],
        30, {"date_prop": "shipDate"},
    )
    for d in DOMAINS:
        bm.namespaces[d] = str(ns(d))

    # Identity graph: 4 entities x 3 KGs, each a 2-edge chain asserted in both directions.
    chains = [
        ("retail:cust_1001", "finance:trader_Alice", "supplychain:consignee_Alice"),
        ("retail:cust_1002", "finance:trader_Bob", "logistics:supplier_Bob"),
        ("logistics:supplier_Acme", "supplychain:carrier_Acme", "energy:site_Acme"),
        ("healthcare:lab_Central", "building:building_Central", "energy:site_Central"),
    ]

    def iri(qname: str) -> URIRef:
        d, local = qname.split(":")
        return ns(d)[local]

    bm.identity.bind("owl", OWL)
    for a, b_, c in chains:
        for x, y in ((a, b_), (b_, c)):
            bm.identity.add((iri(x), OWL.sameAs, iri(y)))
            bm.identity.add((iri(y), OWL.sameAs, iri(x)))
    return bm
