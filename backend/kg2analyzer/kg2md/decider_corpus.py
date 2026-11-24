"""Training corpus for the ML decider: labelled profiles in exactly the shape the KG2MD notebook shows Tev1.

Labels come from construction: an event/transaction name (Sale, Admission, MeterReading ...) is a fact
class and an entity name (Person, Patient, Store ...) a dimension class, whatever structure is drawn for
it. Structure is drawn from overlapping ranges on purpose (people have ages, salaries and links too), so
the classifiers must use what classes and properties are called as well as how they are shaped. Seeded,
so ``python -m kg2analyzer train-decider`` rebuilds the same models.
"""
from __future__ import annotations

import random
import re

# ---------------------------------------------------------------- vocabulary
EVENTS = """Sale SaleTransaction Sales Order OrderLine OrderItem Purchase PurchaseOrder Transaction Payment Transfer
Invoice InvoiceLine Shipment Delivery Booking Reservation Rental Loan Claim InsuranceClaim Admission Visit Encounter
Appointment Prescription Dispense LabTest LabResult Diagnosis Procedure Treatment Vaccination Enrollment Registration
Subscription Renewal Trade Execution Deposit Withdrawal Charge Refund Return Exchange Donation Grant Award Bid Auction
Flight Trip Ride Journey Voyage Departure Arrival Stay CheckIn Session PageView Click Download Login Call Message
Email Ticket Incident Complaint Inspection Audit Review Rating Vote Measurement Reading MeterReading SensorReading
Observation Sample Test Exam ExamResult Grade Score Match Game Race Event Accident Crime Arrest Sentence Hearing Filing
Application Hire Termination Payroll PayrollEntry Timesheet Shift Attendance Absence Leave Expense Budget Allocation
Production ProductionRun Batch Harvest Yield Emission Consumption Usage Load Outage Repair Maintenance WorkOrder
Pick Pack Receipt StockMovement InventoryMovement Adjustment Count Sighting Catch Fishing Planting Census Survey
Response Interview Publication Citation Commit Build Deployment Release Transfer Fact Record Entry Log
Sales Selling Buying Ordering Shopping Spending Earning Funding Financing Investing Borrowing Lending Paying Billing
Invoicing Accrual Posting JournalEntry LedgerEntry Settlement Clearing Reconciliation Transaction Remittance Payout
Commission Bonus Reimbursement Rebate Markdown Promotion Redemption Purchase Acquisition Sale Resale Import Export
Shipment Freight Haulage Transport Transit Leg Segment Stop Pickup Dropoff Loading Unloading Docking Berthing
Treatment Therapy Operation Surgery Consultation Checkup Examination Scan Xray Screening Assessment Evaluation
Admission Discharge Transfer Referral Dosage Administration Injection Vaccination Infusion Transfusion Biopsy
Performance Show Screening Concert Lecture Seminar Workshop Webinar Meeting Conference Interview Hearing Trial
Experiment Run Iteration Simulation Calculation Forecast Prediction Estimate Assessment Valuation Appraisal
Occurrence Happening Incident Outbreak Infection Case Diagnosis Symptom Complaint Request Inquiry Order Query
Purchase Delivery Collection Pickup Drop Swap Trade Deal Contract Agreement Signing Approval Rejection Escalation
Arrival Departure Landing Takeoff Boarding Crossing Passage Entry Exit Visit Stay Overnight Reading Recording
Logging Tracking Monitoring Detection Alarm Alert Notification Reminder Broadcast Transmission Reception""".split()
ENTITIES = """Person People Individual Human Customer Client Consumer Buyer Seller Vendor Supplier Manufacturer
Employee Staff Worker Manager Director Officer Agent Broker Trader Investor Shareholder Patient Doctor Physician Nurse
Surgeon Pharmacist Student Teacher Professor Author Writer Artist Actor Musician Athlete Player Coach Team Club League
Member Subscriber User Account Contact Lead Prospect Partner Organization Organisation Company Corporation Firm
Business Enterprise Bank Branch Store Shop Outlet Warehouse Depot Factory Plant Site Facility Building Room Floor
Office Department Division Unit Region Territory District City Town Village State Province County Country Continent
Address Location Place Area Zone Port Airport Station Route Road Street Product Item Article Good SKU Brand Category
Subcategory Class Family Model Line Collection Book Movie Album Song Course Subject Program Degree School University
College Hospital Clinic Ward Pharmacy Drug Medicine Device Machine Equipment Vehicle Car Truck Ship Aircraft Meter
Sensor Asset Instrument Security Stock Fund Portfolio Currency Unit Language Genre Tag Topic Day Date Week Month
Quarter Semester Year Calendar Time Period Season Holiday Species Animal Plant Crop Farm Field Herd Breed""".split()
# Overlap between the two lists (Unit, Class, Record ...) is resolved by the list order of these sets.
ENTITY_SET = set(ENTITIES) - {"Record", "Entry", "Log", "Fact", "Event"}
EVENT_SET = set(EVENTS)
PREFIXES = ["", "", "", "Retail", "Online", "Customer", "Hospital", "Bank", "Energy", "Store", "Daily", "Monthly",
            "Clinical", "Sales", "Supplier", "Fleet", "Grid", "Student", "Patient", "Freight", "Investment", "Web"]
EVENT_SUFFIXES = ["", "", "", "", "Record", "Event", "Entry", "Line", "Log", "Fact", "Transaction"]
ENTITY_SUFFIXES = ["", "", "", "", "Profile", "Master", "Type", "Group", "Info"]

EVENT_LINKS = """customer client product item store branch employee agent patient doctor physician date day time
month location site meter sensor account supplier vendor carrier vehicle route origin destination channel campaign
promotion currency unit warehouse department ward drug device payer payee sender receiver trader security
broker instrument court judge student course teacher session page user device""".split()
ENTITY_LINKS = """livesIn worksFor memberOf belongsTo locatedIn partOf category subcategory parent manager
department country city region employer spouse nationality brand manufacturer reportsTo headquarters
homeTown birthPlace school team club owner""".split()
EVENT_NUMERIC = """amount totalAmount saleTotalAmount quantity qty unitsSold price unitPrice discount tax fee charge
cost totalCost revenue profit margin duration durationMinutes hours weight weightKg distanceKm volume
energyKwh consumption reading value temperature humidity score result resultValue shareCount tradeAmount
transferAmount paidAmount refundAmount lineTotal freight shipping leadTimeDays transitDays waitMinutes
occupancy count""".split()
ENTITY_NUMERIC = """age ageYears salary income annualIncome population area areaKm2 capacity height weight
rating stars foundedYear yearFounded employeeCount headcount creditLimit listPrice stockLevel latitude
longitude elevation budget numberOfBeds seats floors yearsOfExperience gpa birthYear""".split()

SUM_MEASURES = """amount totalAmount saleTotalAmount salesAmount revenue sales quantity qty unitsSold itemsSold
count visits calls orders shares shareCount tradeAmount transferAmount paidAmount refundAmount cost totalCost
fee fees charge charges tax taxAmount freight freightCost shippingCost profit netProfit grossProfit lineTotal
volume volumeLitres energyKwh energyConsumedKwh consumption distanceKm distanceMiles weightKg shipmentWeightKg
tonnes hoursWorked minutesUsed overtimeHours deposits withdrawals donations emissionsTons occupancyCount
passengers ticketsSold downloads clicks views budgetSpent expense expenses premium claimsPaid""".split()
AVG_MEASURES = """price unitPrice avgPrice averagePrice rate interestRate exchangeRate ratio percent pct share
discount discountRate score rating satisfaction satisfactionScore temperature temperatureCelsius humidity
humidityPct speed avgSpeed pressure density age index priceIndex level voltage voltageLevel margin marginPct
yield efficiency occupancyRate utilization accuracy precision probability bmi heartRate bloodPressure
resultScoreRatio gpa grade latencyMs responseTimeMs leadTimeDays transitDays turnaroundHours waitMinutes
durationDays tenureYears elevation latitude longitude""".split()
MIN_MEASURES = """minPrice minimumPrice minTemperature lowestPrice lowTemperature minValue earliestDate floorPrice
minimumBalance minStock lowWatermark minLatency minimumScore""".split()
MAX_MEASURES = """maxPrice maximumPrice maxTemperature peakDemandKw peakLoad highestPrice highTemperature maxValue
capacity maxCapacity maxSpeed topSpeed ceiling maximumScore peakUsers maxLatency highWatermark recordHigh""".split()

UNIT_NAMES = """unit unitOfMeasure uom measurementUnit hasUnit measuredIn currency priceCurrency
amountCurrency denomination unitCode quantityUnit weightUnit temperatureUnit energyUnit volumeUnit
distanceUnit timeUnit currencyCode""".split()
UNIT_VALUES = """kg kilogram g gram tonne lb EUR USD GBP BDT JPY kWh MWh Wh litre liter ml m3 meter metre km
mile celsius fahrenheit kelvin percent second minute hour day pcs piece each""".split()
NON_UNIT_NAMES = """customer product category city country store branch employee supplier brand department
manager owner businessUnit storageUnit housingUnit unitOwner unitManager operatingUnit organizationalUnit
militaryUnit rentalUnit unitLeader team region route carrier channel account""".split()
NON_UNIT_VALUES = """cust_1001 prod_42 cat_books dhaka chittagong store_7 emp_15 bu_north unit_12 unit_A3 team_red
region_east route_9 acme_corp gold_tier apt_4B ward_2""".split()

ATTRIBUTE_NAMES = """name label title fullName firstName lastName code id identifier sku isbn email phone address
street postcode zip city description summary brand color colour size gender dateOfBirth birthDate foundedYear
population area capacity website url category nickname alias shortName displayName registrationNumber
taxId licenseNumber model manufacturer""".split()
METADATA_NAMES = """createdAt created createdOn createdBy updatedAt updated modifiedAt lastModified modifiedBy
version revision batchId batchNumber jobId etlRunId runId loadDate loadedAt ingestedAt importedAt importedBy
sourceSystem sourceFile sourceTable checksum hash md5 syncedAt lastSync deleted isDeleted deletedFlag
recordStatus rowVersion dataSteward steward provenanceNote validFromLoad""".split()

ANALYSIS_GOAL = "Identify the central observation records for the cube"


def _camel(*parts: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _lower_camel(s: str) -> str:
    return s[:1].lower() + s[1:]


# ---------------------------------------------------------------- generators
def fact_examples(rng: random.Random, n: int, names: tuple[list[str], list[str]] | None = None) -> list[tuple[dict, str]]:
    events, entities = names or (EVENTS, ENTITIES)
    out = []
    for _ in range(n):
        fact = rng.random() < 0.5
        base = rng.choice(events if fact else entities)
        if fact and base in ENTITY_SET and base not in EVENT_SET:
            continue
        name = _camel(rng.choice(PREFIXES), base, rng.choice(EVENT_SUFFIXES if fact else ENTITY_SUFFIXES))
        if fact:
            n_obj, n_num = rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5, 6]), rng.choice([0, 1, 1, 2, 2, 3, 3, 4, 5])
            inst = rng.choice([5, 20, 60, 200, 1_000, 10_000, 250_000])
        else:
            n_obj, n_num = rng.choice([0, 0, 1, 1, 2, 2, 3, 4]), rng.choice([0, 0, 1, 1, 2, 2, 3, 4])
            inst = rng.choice([2, 5, 12, 40, 150, 800, 5_000, 60_000])
        objs = rng.sample(EVENT_LINKS if fact else ENTITY_LINKS, n_obj)
        if not fact and rng.random() < 0.3:  # entities that point at other entities through event-like names too
            objs = objs[:-1] + [rng.choice(EVENT_LINKS)] if objs else objs
        nums = rng.sample(EVENT_NUMERIC if fact else ENTITY_NUMERIC, n_num)
        if rng.random() < 0.5:  # same structure for both kinds: only the name can decide
            n_obj, n_num = rng.choice([1, 2, 2, 3]), rng.choice([0, 1, 2, 2, 3])
            inst = rng.choice([10, 50, 120, 500, 2_000])
            objs = rng.sample(EVENT_LINKS + ENTITY_LINKS, n_obj)
            nums = rng.sample(EVENT_NUMERIC + ENTITY_NUMERIC, n_num)
        out.append(({
            "analysis_goal": ANALYSIS_GOAL, "class_name": name, "instance_count": inst,
            "object_property_count": len(objs), "numeric_property_count": len(nums),
            "object_properties": [{"name": o, "range": _camel(o)} for o in objs],
            "numeric_properties": [{"name": m, "datatype": f"http://www.w3.org/2001/XMLSchema#{rng.choice(['decimal', 'integer', 'double'])}"}
                                   for m in nums],
        }, "fact_class" if fact else "dimension_class"))
    return out


def aggregate_examples(rng: random.Random, n: int) -> list[tuple[dict, str]]:
    pools = [("sum", SUM_MEASURES), ("avg", AVG_MEASURES), ("min", MIN_MEASURES), ("max", MAX_MEASURES)]
    weights = [0.4, 0.4, 0.1, 0.1]
    out = []
    for _ in range(n):
        label, pool = rng.choices(pools, weights)[0]
        name = rng.choice(pool)
        if rng.random() < 0.25:
            name = _lower_camel(_camel(rng.choice(["sale", "line", "order", "trade", "daily", "monthly", "total", "net"]), name)) \
                if label == "sum" else name
        bounded = label == "avg" and any(w in name.lower() for w in ("ratio", "pct", "percent", "rate", "share", "probability", "accuracy", "utilization")) \
            and rng.random() < 0.8
        out.append(({"measure_name": name, "datatype": rng.choice(["decimal", "integer", "double", "float"]),
                     "unit": rng.choice(["none", "none", "EUR", "kWh", "kg", "percent", "celsius", "hour"]),
                     "values_between_0_and_1": bounded}, label))
    return out


def unit_examples(rng: random.Random, n: int) -> list[tuple[dict, str]]:
    out = []
    for _ in range(n):
        unit = rng.random() < 0.4
        name = rng.choice(UNIT_NAMES if unit else NON_UNIT_NAMES)
        values = rng.sample(UNIT_VALUES if unit else NON_UNIT_VALUES, rng.choice([1, 2, 3]))
        out.append(({"property_name": name, "label": rng.choice(["", name]),
                     "range": rng.choice(["Unit", "UnitOfMeasure", "Currency", "unknown"]) if unit else _camel(name.split("Unit")[0] or "Thing"),
                     "example_values": values}, "unit_property" if unit else "other_property"))
    return out


def attribute_examples(rng: random.Random, n: int) -> list[tuple[dict, str]]:
    out = []
    for _ in range(n):
        attr = rng.random() < 0.6
        name = rng.choice(ATTRIBUTE_NAMES if attr else METADATA_NAMES)
        out.append(({"property_name": name, "datatype": rng.choice(["string", "integer", "date", "dateTime", "decimal"]),
                     "level": rng.choice(ENTITIES), "example_values": []}, "attribute" if attr else "metadata"))
    return out


def corpus(seed: int = 7, scale: int = 1) -> dict[str, list[tuple[dict, str]]]:
    rng = random.Random(seed)
    return {"fact_class": fact_examples(rng, 3000 * scale), "aggregate": aggregate_examples(rng, 2500 * scale),
            "unit": unit_examples(rng, 1200 * scale), "level_attribute": attribute_examples(rng, 1200 * scale)}


def split_words(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return " ".join(t for t in re.split(r"[^a-z0-9]+", text.lower()) if t)
