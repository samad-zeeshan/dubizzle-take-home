# Inventory enrichment report

Generated 2026-09-07 10:19 UTC from `cars.xlsx` (sha256 94a97f84aa74).
LLM enrichment: yes, gemini/gemini-3.5-flash-lite.

## Sheets and columns

| sheet | kind | rows | core columns | optional columns | unmapped |
|---|---|---|---|---|---|
| cleaned dataset | cleaned | 100 | make=make, model=model, trim=trim, year=year, title=title, description=description, photo_url=photo_url, listing_id=Listing_ID | none | none |
| raw dataset | raw | 100 | make=make, model=model, trim=trim, year=year, title=title, description=description, photo_url=photo_url | none | none |

0 field values came straight from columns and outrank the text extractor.

## Rows

| stage | cleaned sheet | raw sheet |
|---|---|---|
| read from workbook | 100 | 100 |
| kept after dedup | 100 | 89 |

Total listings: **189**, 46 makes, years 2003 to 2026.

### Duplicates removed

| reason | kept | dropped row | title |
|---|---|---|---|
| exact duplicate within raw | 8 | 40 | 4,000 P.M | 0% DownPayment | Under Warranty | SummerOffer ABT BodyKit |
| exact duplicate within raw | 8 | 41 | 4,000 P.M | 0% DownPayment | Under Warranty | SummerOffer ABT BodyKit |
| exact duplicate within raw | 8 | 42 | 4,000 P.M | 0% DownPayment | Under Warranty | SummerOffer ABT BodyKit |
| exact duplicate within raw | 14 | 63 | RANGE ROVER SPORT V8 * FULL OPTIONS * GCC SPEC * PANORAMIC * WELL_MAIN |
| exact duplicate within raw | 69 | 70 | TOVA J14 3.0 TON 2.8L Chassis 2025 Model available only for export |
| exact duplicate within raw | 8 | 77 | 4,000 P.M | 0% DownPayment | Under Warranty | SummerOffer ABT BodyKit |
| exact duplicate within raw | 76 | 82 | 3,000 PM | 0% Down-Payment | Land Rover Warranty | SummerOffer SUNROOF |
| exact duplicate within raw | 44 | 84 | معرض بن برغش للسيارات أبوظبي مدينة بني ياس |
| exact duplicate within raw | 80 | 96 | AED 2,340 P.M | 2024 BMW i4 Gran Coupé eDrive35 MSport | BMW Warranty  |
| exact duplicate within raw | 6 | 97 | Haval H9 2026 GCC specs | Agency Warranty |
| same listing in both sheets (photo_url), cleaned copy kept | C-059 | 62 | Urgent mini countryman S model 2014 GCC panorama very clean |

## Field coverage

| field | known | column | regex | inferred | derived | llm | override |
|---|---|---|---|---|---|---|---|
| price_aed | 40 (21%) | 0 | 30 | 0 | 0 | 10 | 0 |
| monthly_aed | 38 (20%) | 0 | 38 | 0 | 0 | 0 | 0 |
| price_vat_status | 4 (2%) | 0 | 4 | 0 | 0 | 0 | 0 |
| down_payment_pct | 38 (20%) | 0 | 38 | 0 | 0 | 0 | 0 |
| mileage_km | 91 (48%) | 0 | 77 | 0 | 0 | 14 | 0 |
| is_brand_new | 16 (8%) | 0 | 13 | 0 | 3 | 0 | 0 |
| exterior_color | 67 (35%) | 0 | 54 | 0 | 0 | 13 | 0 |
| interior_color | 54 (28%) | 0 | 25 | 0 | 0 | 29 | 0 |
| body_type | 189 (100%) | 0 | 21 | 167 | 0 | 1 | 0 |
| regional_spec | 126 (66%) | 0 | 126 | 0 | 0 | 0 | 0 |
| fuel_type | 180 (95%) | 0 | 21 | 2 | 0 | 157 | 0 |
| transmission | 166 (87%) | 0 | 67 | 0 | 0 | 99 | 0 |
| seats | 110 (58%) | 0 | 12 | 0 | 0 | 98 | 0 |
| has_warranty | 55 (29%) | 0 | 55 | 0 | 0 | 0 | 0 |
| warranty_text | 55 (29%) | 0 | 55 | 0 | 0 | 0 | 0 |
| service_contract | 24 (12%) | 0 | 24 | 0 | 0 | 0 | 0 |
| is_export_only | 3 (1%) | 0 | 3 | 0 | 0 | 0 | 0 |
| is_dubizzle_managed | 10 (5%) | 0 | 10 | 0 | 0 | 0 | 0 |

## Price picture

- Cash price stated: 40 (21%)
- Monthly instalment only: 8 (4%)
- No price at all: 141 (74%)

## Rejected numbers

Figures that looked like a price or an odometer reading but were rejected by context.

| listing | value | reason | snippet |
|---|---|---|---|
| C-013 | 1,000 | decoy context | ox. 2.5% for Car insurance.  AED 1,000 – Evaluation.  AED 1,200 – R |
| C-013 | 1,200 | decoy context | .  AED 1,000 – Evaluation.  AED 1,200 – RTA/Car registration fee. O |
| C-015 | 18,845 | range, warranty, service or speed context | erior Color: Black and orange Odometer: 18,845 (kms) WARRANTY AVAILABLE Spec |
| C-022 | 16,000 | range, warranty, service or speed context | KM * 2 YEAR SERVICE CONTRACT (16000 Km or 1 year, whichever comes fi |
| C-032 | 1 | out of price range | s are bank auto loans. Option 1 - AED 1,750 monthly for 4 years wit |
| C-032 | 2 | out of price range | wn-Payment / flexible. Option 2 - AED 1,400 monthly for 4 years wit |
| C-032 | 3 | out of price range | wn-Payment / flexible. Option 3 - AED 70,000 cash And First Install |
| C-032 | 100,271 | range, warranty, service or speed context | r F-Pace 25T AWD Model : 2019 Odometer : 100,271 Kms Warranty : 3rd Party (3 Y |
| C-042 | 23,895 | range, warranty, service or speed context | s Last Service: 18/05/2026 or 23,895 Kms (AGMC) Next Service: 18/05/20 |
| C-044 | 102,000 | range, warranty, service or speed context | ime. Key Features: Year: 2019 Mileage: 102,000 km Transmission: 8-speed Auto |
| C-047 | 104,700 | range, warranty, service or speed context | s Last Service: 22/08/2023 or 104,700 Kms (ABD) Next Service: 22/08/202 |
| C-047 | 114,700 | range, warranty, service or speed context | ) Next Service: 22/08/2024 or 114,700 Kms This 2017 Maserati Levante S |
| C-060 | 32,000 | decoy context | 0 km -Well Maintained Price # 32000 Aed Service we provide: Assistanc |
| C-065 | 71,000 | range, warranty, service or speed context | Dodge Challenger 2021 71000 KM Warranty SXT |
| C-066 | 1 | out of price range | s are bank auto loans. Option 1 - AED 1650 monthly for 5 years with |
| C-066 | 2 | out of price range | wn-Payment / flexible. Option 2 - AED 1300 monthly for 5 years with |
| C-066 | 3 | out of price range | wn-Payment / flexible. Option 3 - AED 79,999 cash. And First Instal |
| C-068 | 30,000 | range, warranty, service or speed context | 2 years Free servicing (up to 30,000 km*) Free vehicle registration - |
| C-088 | 1 | out of price range | s are bank auto loans. Option 1 - AED 2,300 monthly for 5 years wit |
| C-088 | 2 | out of price range | wn-Payment / flexible. Option 2 - AED 1,850 monthly for 5 years wit |
| C-088 | 3 | out of price range | wn-Payment / flexible. Option 3 - AED 115,000 cash. And First Insta |
| C-088 | 15,858 | range, warranty, service or speed context | ndai Genesis G80 Model : 2023 Odometer : 15,858 Kms Warranty : 3rd Party (2 Y |
| C-092 | 23,900 | range, warranty, service or speed context | es-Benz GLS 63 AMG Year: 2021 Mileage: 23 900 kms Exterior: Diamond White I |
| C-095 | 1 | out of price range | s are bank auto loans. Option 1 - AED 1,950 monthly for 5 years wit |
| C-095 | 2 | out of price range | wn-Payment / flexible. Option 2 - AED 1,500 monthly for 5 years wit |
| C-095 | 3 | out of price range | wn-Payment / flexible. Option 3 - AED 95,000 cash. And First Instal |
| C-095 | 970 | range, warranty, service or speed context | a Wildlander AWD Model : 2023 Odometer : 970 Kms Warranty : 3rd Party (2 Y |
| R-003 | 100,000 | range, warranty, service or speed context | Ford warranty until 6/2028 or 100,000 kms Ford Service Plan until 6/202 |
| R-003 | 100,000 | range, warranty, service or speed context | Service Plan until 6/2028 or 100,000 kms GCC Specification Trade-In or |
| R-005 | 200,000 | range, warranty, service or speed context | cy Warranty covers 6 years or 200,000 km, ensuring peace of mind. Flex |
| R-007 | 89,000 | range, warranty, service or speed context | ABT Sport Body Kit ⸻ Details: Mileage: 89,000 KM Warranty: 1 Year Premium W |
| R-014 | 701 | range, warranty, service or speed context | an L EV offers an exceptional 701KM range on a single charge, tha |
| R-014 | 701 | range, warranty, service or speed context | YD Blade Battery for extended 701KM driving range Performance: In |
| R-015 | 17,611 | range, warranty, service or speed context | VEHICLE SPECS: Last Service: 17,611 Km (Jun-2025) Next Service: 32,6 |
| R-015 | 32,611 | range, warranty, service or speed context | 1 Km (Jun-2025) Next Service: 32,611 Km (Jun-2026) GCC Specs 5 Doors |
| R-023 | 37,062 | range, warranty, service or speed context | 20% Down payment for 5 Years Mileage: 37,062 km Warranty: BMW Warranty val |
| R-037 | 200,000 | range, warranty, service or speed context | he following: Bal: 5 Years or 200,000 km BMW Warranty. Bal: 5 Years or |
| R-037 | 100,000 | range, warranty, service or speed context | BMW Warranty. Bal: 5 Years or 100,000 km BMW Service Package. Free 1st |
| R-044 | 93,000 | decoy context | Boost Under Ford Warranty GCC 93,000 AED GCC Specs Full Service Histor |
| R-044 | 100,000 | range, warranty, service or speed context | arranty Till February 2029 or 100,000 km (Al Tayer Motors) Ford Servic |
| R-044 | 100,000 | range, warranty, service or speed context | ontract Till February 2029 or 100,000 km (Al Tayer Motors) Engine Spec |
| R-044 | 34,000 | range, warranty, service or speed context | VEHICLE SPECS: Last Service: 34,000 Km (05/02/2026) Next Service: 43 |
| R-044 | 43,000 | range, warranty, service or speed context | Km (05/02/2026) Next Service: 43,000 Km (05/08/2026) GCC Specs 5 Door |
| R-045 | 1 | out of price range | nce Options Available: Option 1 - AED 3,413 P/M for 5 years with 0% |
| R-045 | 2 | out of price range | rs with 0% Downpayment Option 2 - AED 2,731 P/M for 5 years with 20 |
| R-045 | 105,000 | range, warranty, service or speed context | GARGASH WARRANTY UNTIL 2029 / 105,000 KM GARGASH SERVICE CONTRACT UNTI |
| R-045 | 105,000 | range, warranty, service or speed context | SERVICE CONTRACT UNTIL 2029 / 105,000 KM Experience the epitome of lux |
| R-052 | 26,106 | range, warranty, service or speed context | nty Included Service Contract 26106 kms Warranty until August 2028 or |
| R-052 | 40,000 | range, warranty, service or speed context | s Service Contract Valid till 40,000 Kms 1. Grey with Leather Interior |
| R-056 | 1 | out of price range | s are bank auto loans. Option 1 - AED 3,350 monthly for 5 years wit |
| R-056 | 2 | out of price range | wn-Payment / flexible. Option 2 - AED 2,650 monthly for 5 years wit |
| R-056 | 3 | out of price range | wn-Payment / flexible. Option 3 - AED 165,000 cash. And First Insta |
| R-069 | 69,000 | range, warranty, service or speed context | ed Safety Features ⸻ Details: Mileage: 69,000 KM Warranty: Land Rover (Al T |
| R-069 | 150,000 | range, warranty, service or speed context | Warranty untill 28/09/2027 or 150,000 km ⸻ Why This Range Rover Evoque |
| R-069 | 150,000 | range, warranty, service or speed context | ver (Al Tayer ) 28/09/2027 or 150,000 km Service: Can Be Added Ownersh |
| R-070 | 3,000 | decoy context | cessible to All: requirement: AED 3000 (WPS) Accepts both Savings an |
| R-070 | 3,000 | out of price range | e Documentation: Certificate (AED 3000 and More) Last 03 Month’s For |
| R-072 | 179,000 | decoy context | rranty & Service Contract GCC 179,000 AED GCC Specs Full Service Histor |
| R-072 | 200,000 | range, warranty, service or speed context | Warranty Until 28/05/2029 or 200,000 KM BMW Service Contract Until 28 |
| R-072 | 483 | range, warranty, service or speed context | (Usable) Driving Range: Up to 483 km (WLTP) Home Charging (AC 11 k |
| R-074 | 60,000 | range, warranty, service or speed context | /2027 Warranty: 13/09/2026 or 60,000 Kms (German Experts) This 2021 Fe |
| R-085 | 39,000 | range, warranty, service or speed context | 0% Down Payment over 5 Years. Mileage 39000 Kms FREE Registration Comes W |
| R-086 | 105,000 | range, warranty, service or speed context | rranty: Until 24-June-2029 or 105,000 KM Service Contract: Until 25-Ju |
| R-086 | 105,000 | range, warranty, service or speed context | ntract: Until 25-June-2029 or 105,000 KM Wheel Size: 21" Why Choose Th |

## Regex versus LLM disagreements

| listing | field | regex | llm | resolution |
|---|---|---|---|---|
| C-003 | monthly_aed | 1876 | 2111 | regex kept (has evidence) |
| C-015 | exterior_color | orange | black | llm used (regex confidence low) |
| C-027 | mileage_km | 2 | 75500 | regex kept (has evidence) |
| C-038 | exterior_color | black | yellow | llm used (regex confidence low) |
| C-044 | monthly_aed | 2503 | 2816 | regex kept (has evidence) |
| C-071 | mileage_km | 3 | 71000 | regex kept (has evidence) |
| C-092 | exterior_color | black | diamond white | llm used (regex confidence low) |
| C-095 | monthly_aed | 1500 | 1950 | regex kept (has evidence) |
| R-005 | monthly_aed | 1813 | 2040 | regex kept (has evidence) |
| R-007 | monthly_aed | 2700 | 4000 | regex kept (has evidence) |
| R-025 | exterior_color | grey | white | llm used (regex confidence low) |
| R-032 | exterior_color | grey | burgundy | llm used (regex confidence low) |
| R-038 | exterior_color | black | light blue & nocturne | llm used (regex confidence low) |
| R-045 | monthly_aed | 2731 | 3413 | regex kept (has evidence) |
| R-050 | mileage_km | 2024 | 0 | regex kept (has evidence) |
| R-053 | exterior_color | black | red | llm used (regex confidence low) |
| R-069 | monthly_aed | 2400 | 3000 | regex kept (has evidence) |
| R-079 | mileage_km | 128 | 128000 | regex kept (has evidence) |

## Flags

- dubizzle managed boilerplate: 10: R-006, R-016, R-036, R-041, R-052, R-057, R-062, R-077, R-082, R-089
- export only: 3: R-027, R-047, R-063
- brand new: 16: C-027, C-028, C-033, C-054, C-066, C-071, C-084, C-086, R-002, R-005, R-012, R-013, R-031, R-056, R-080, R-086
- Arabic only: 13: C-019, C-023, C-035, C-067, C-078, R-004, R-018, R-025, R-040, R-053, R-055, R-066, R-073
- mixed language: 10: C-007, C-026, C-031, C-093, C-098, R-008, R-032, R-059, R-067, R-080
- truncated description: 26: C-019, C-049, R-005, R-006, R-007, R-012, R-014, R-016, R-023, R-026, R-035, R-036, R-041, R-045, R-052, R-054, R-056, R-057, R-062, R-069, R-070, R-072, R-077, R-082, R-083, R-089
- minimal description: 11: C-002, C-016, C-028, C-031, C-035, C-048, C-067, C-069, R-047, R-066, R-075
- boilerplate description: 3: C-030, C-074, C-100
- contact details stripped: 104: C-002, C-004, C-005, C-007, C-012, C-013, C-014, C-015, C-017, C-020, C-024, C-026, C-027, C-028, C-029, C-030, C-032, C-034, C-039, C-040, C-042, C-047, C-050, C-051, C-052, C-053, C-054, C-055, C-057, C-058, C-062, C-063, C-066, C-068, C-070, C-071, C-072, C-074, C-076, C-077, C-081, C-083, C-085, C-088, C-089, C-092, C-093, C-095, C-096, C-097, C-098, C-099, C-100, R-001, R-002, R-003, R-006, R-007, R-008, R-012, R-015, R-016, R-017, R-018, R-019, R-020, R-021, R-022, R-023, R-025, R-026, R-030, R-033, R-034, R-035, R-036, R-037, R-041, R-044, R-050, R-051, R-052, R-053, R-054, R-056, R-057, R-058, R-060, R-061, R-062, R-063, R-064, R-065, R-067, R-069, R-072, R-073, R-074, R-077, R-078, R-082, R-083, R-087, R-089

## Known quirks

- There is no price column. Prices live in free text and most listings have none.
- The two sheets are different listings, not raw and clean versions of the same rows. One car overlaps.
- Cleaned Listing_ID 52 says 2015 in the year column and 2014 in the title. The column wins.
- Mazda model '3' and Aston Martin DBX trim '707' are integers in the workbook and are cast to text.
- Ten raw listings carry dubizzle's managed-inventory boilerplate. That block is the is_dubizzle_managed marker.
- The BYD Han L repeats '701KM' six times. It is battery range, not mileage, and is rejected as such.
- Dealer opening hours in descriptions include Sundays. They are removed and never used for booking.
