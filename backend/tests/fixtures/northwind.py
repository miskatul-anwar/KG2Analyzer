"""Instantiated Northwind Enterprise Reference Corpus (thesis section 3.3.1).

18 classes following the Northwind DW of Vaisman & Zimanyi (ADW, ch. 4). The
10 ``Sales`` facts reproduce the relational ground-truth roll-up of
Table 4.2: Beverages 541.00, Condiments 2,865.69, Meat/Poultry 388.00,
Produce 342.00, Seafood 471.20 (total 4,607.89).
"""
from __future__ import annotations

from decimal import Decimal

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS, XSD

from fixtures.enterprise import UNIT

NW = Namespace("http://example.org/northwind#")

CATEGORY_TOTALS = {
    "Beverages": Decimal("541.00"),
    "Condiments": Decimal("2865.69"),
    "Meat/Poultry": Decimal("388.00"),
    "Produce": Decimal("342.00"),
    "Seafood": Decimal("471.20"),
}

# (product, category, sales total amounts for the facts that sell it)
_SALES = [
    ("Chai", "Beverages", ["216.00", "325.00"]),
    ("Aniseed Syrup", "Condiments", ["1265.69"]),
    ("Chef Anton's Gumbo Mix", "Condiments", ["800.00", "800.00"]),
    ("Mishi Kobe Niku", "Meat/Poultry", ["388.00"]),
    ("Tofu", "Produce", ["342.00"]),
    ("Ikura", "Seafood", ["271.20", "120.00", "80.00"]),
]


def build_northwind() -> Graph:
    g = Graph()
    g.bind("northwind", NW)

    def cls(name):
        g.add((NW[name], RDF.type, OWL.Class))
        g.add((NW[name], RDFS.label, Literal(name)))
        return NW[name]

    def op(name, d, r):
        g.add((NW[name], RDF.type, OWL.ObjectProperty))
        g.add((NW[name], RDFS.domain, d))
        g.add((NW[name], RDFS.range, r))
        return NW[name]

    def dp(name, d, dt, unit=None):
        g.add((NW[name], RDF.type, OWL.DatatypeProperty))
        g.add((NW[name], RDFS.domain, d))
        g.add((NW[name], RDFS.range, dt))
        if unit:
            g.add((NW[name], UNIT, Literal(unit)))
        return NW[name]

    def inst(local, c, label=None):
        g.add((NW[local], RDF.type, c))
        if label:
            g.add((NW[local], RDFS.label, Literal(label)))
        return NW[local]

    C = {n: cls(n) for n in (
        "Sales", "Time", "Product", "Year", "Country", "Order", "Employee", "Category", "Month",
        "Customer", "City", "Quarter", "Shipper", "Region", "Semester", "State", "Supplier", "Continent")}

    P = {
        "product": op("product", C["Sales"], C["Product"]),
        "customer": op("customer", C["Sales"], C["Customer"]),
        "employee": op("employee", C["Sales"], C["Employee"]),
        "orderDate": op("orderDate", C["Sales"], C["Time"]),
        "shipper": op("shipper", C["Sales"], C["Shipper"]),
        "supplier": op("supplier", C["Sales"], C["Supplier"]),
        "order": op("order", C["Sales"], C["Order"]),
        "category": op("category", C["Product"], C["Category"]),
        "month": op("month", C["Time"], C["Month"]),
        "quarter": op("quarter", C["Month"], C["Quarter"]),
        "semester": op("semester", C["Quarter"], C["Semester"]),
        "year": op("year", C["Semester"], C["Year"]),
        "customerCity": op("customerCity", C["Customer"], C["City"]),
        "supplierCity": op("supplierCity", C["Supplier"], C["City"]),
        "employeeCity": op("employeeCity", C["Employee"], C["City"]),
        "supervisor": op("supervisor", C["Employee"], C["Employee"]),
        "territoryRegion": op("territoryRegion", C["Employee"], C["Region"]),
        "cityState": op("cityState", C["City"], C["State"]),
        "cityCountry": op("cityCountry", C["City"], C["Country"]),
        "stateCountry": op("stateCountry", C["State"], C["Country"]),
        "countryContinent": op("countryContinent", C["Country"], C["Continent"]),
    }
    M = {
        "unitPrice": dp("unitPrice", C["Sales"], XSD.decimal, "USD"),
        "quantity": dp("quantity", C["Sales"], XSD.integer, "count"),
        "discount": dp("discount", C["Sales"], XSD.decimal, "ratio"),
        "extendedPrice": dp("extendedPrice", C["Sales"], XSD.decimal, "USD"),
        "freight": dp("freight", C["Sales"], XSD.decimal, "USD"),
        "salesTotalAmount": dp("salesTotalAmount", C["Sales"], XSD.decimal, "USD"),
    }

    # Geography (ragged: Seattle has a state, Berlin skips straight to its country)
    europe = inst("continent_Europe", C["Continent"], "Europe")
    america = inst("continent_America", C["Continent"], "North America")
    germany = inst("country_Germany", C["Country"], "Germany")
    usa = inst("country_USA", C["Country"], "USA")
    g.add((germany, P["countryContinent"], europe))
    g.add((usa, P["countryContinent"], america))
    wa = inst("state_WA", C["State"], "Washington")
    g.add((wa, P["stateCountry"], usa))
    seattle = inst("city_Seattle", C["City"], "Seattle")
    g.add((seattle, P["cityState"], wa))
    berlin = inst("city_Berlin", C["City"], "Berlin")
    g.add((berlin, P["cityCountry"], germany))

    # Time: Time -> Month -> Quarter -> Semester -> Year
    y = inst("year_1997", C["Year"], "1997")
    s1 = inst("sem_1997_1", C["Semester"], "1997-S1")
    g.add((s1, P["year"], y))
    q1 = inst("q_1997_1", C["Quarter"], "1997-Q1")
    g.add((q1, P["semester"], s1))
    months = []
    for m in (1, 2, 3):
        mm = inst(f"month_1997_{m:02d}", C["Month"], f"1997-{m:02d}")
        g.add((mm, P["quarter"], q1))
        months.append(mm)

    # People and organisations
    emea = inst("region_EMEA", C["Region"], "EMEA")
    amer = inst("region_AMER", C["Region"], "Americas")
    boss = inst("emp_Fuller", C["Employee"], "Andrew Fuller")
    g.add((boss, P["employeeCity"], seattle))
    g.add((boss, P["territoryRegion"], amer))
    emp = inst("emp_Davolio", C["Employee"], "Nancy Davolio")
    g.add((emp, P["supervisor"], boss))
    g.add((emp, P["employeeCity"], seattle))
    g.add((emp, P["territoryRegion"], amer))
    g.add((emp, P["territoryRegion"], emea))  # nonstrict
    cust_a = inst("cust_ALFKI", C["Customer"], "Alfreds Futterkiste")
    g.add((cust_a, P["customerCity"], berlin))
    cust_b = inst("cust_GREAL", C["Customer"], "Great Lakes Food Market")
    g.add((cust_b, P["customerCity"], seattle))
    sup = inst("sup_Exotic", C["Supplier"], "Exotic Liquids")
    g.add((sup, P["supplierCity"], berlin))
    ship = inst("ship_Speedy", C["Shipper"], "Speedy Express")

    cats = {}
    for name in CATEGORY_TOTALS:
        cats[name] = inst("cat_" + name.replace("/", "_"), C["Category"], name)

    n = 0
    for p_i, (pname, cat, totals) in enumerate(_SALES):
        prod = inst(f"prod_{p_i + 1}", C["Product"], pname)
        g.add((prod, P["category"], cats[cat]))
        for total in totals:
            n += 1
            total_d = Decimal(total)
            freight = (total_d * Decimal("0.05")).quantize(Decimal("0.01"))
            ext = total_d - freight
            qty = 2 + n % 4
            disc = Decimal("0.05") if n % 3 == 0 else Decimal("0")
            price = (ext / qty / (1 - disc)).quantize(Decimal("0.01"))
            day = inst(f"day_1997_{(n % 3) + 1:02d}_{n:02d}", C["Time"], f"1997-{(n % 3) + 1:02d}-{n:02d}")
            g.add((day, P["month"], months[n % 3]))
            order = inst(f"order_{10247 + n}", C["Order"], f"Order {10247 + n}")
            s = inst(f"sale_{n:02d}", C["Sales"])
            for prop, obj in (("product", prod), ("customer", cust_a if n % 2 else cust_b),
                              ("employee", emp if n % 2 else boss), ("orderDate", day), ("shipper", ship),
                              ("supplier", sup), ("order", order)):
                g.add((s, P[prop], obj))
            for prop, val, dt in (("unitPrice", price, XSD.decimal), ("quantity", qty, XSD.integer),
                                  ("discount", disc, XSD.decimal), ("extendedPrice", ext, XSD.decimal),
                                  ("freight", freight, XSD.decimal), ("salesTotalAmount", total_d, XSD.decimal)):
                g.add((s, M[prop], Literal(val, datatype=dt)))
    return g
