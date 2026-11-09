# Jersey City Autonomous Mobility Power Map

_As of 2026-11-09. Who can enable, block, or shape driverless AV service on Jersey City streets?_

Scores: **power** 1-5: ability to enable/block AV ops in JC (5 = can legally allow/stop it) · **interest** 1-5: how actively engaged on AVs in NJ/JC (5 = core business or active lobbying) · **stance** -2..+2 toward driverless AV deployment in JC; 0 = neutral or no public position found

## So what

1. The decision sits with the state, not the city. Nothing driverless runs in JC until S1677/A3968 clears Senate Budget & Appropriations and both floors, and Gov. Sherrill signs it. After that, MVC holds a halt power over every operator.
2. The bill picks winners. Waymo's sensor stack complies (after a human-driver phase). Tesla's camera-only Robotaxi and pedal-less Cybercab do not.
3. The city's levers are the curb and Via. JC's deficit of about $90M already cut Via's hours. The Waymo-Via Chandler model is the cheapest local entry point, and the Mayor, Kaplan and the Council control it.
4. The biggest gap: the City, Bike JC and Safe Streets JC have no public AV position. The reinstated Vision Zero Task Force is where that position will form.

## Power map

| Stakeholder | Power | Interest | Stance | Quadrant | Lever |
|---|:-:|:-:|---|---|---|
| ★ NJ MVC (Acting Chief Admin. Rosalie Johnson) | 5 | 3 | Neutral/unknown (0) | Manage closely | Permitting, the halt ('kill switch') power, and pilot rulemaking. |
| Gov. Mikie Sherrill | 5 | 1 | Neutral/unknown (0) | Keep satisfied | Signature or veto; agency direction. |
| ★ Waymo | 4 | 5 | Champion (+2) | Manage closely | Shaping S1677/A3968 amendments; Port Authority airport partnership; Via transit integration. |
| Sen. Andrew Zwicker (S1677 prime sponsor) | 4 | 5 | Supportive (+1) | Manage closely | Bill text: sensor mandate, safety-driver phase, school-zone limits. |
| ★ NJ Transit (CEO Kris Kolluri) | 4 | 2 | Neutral/unknown (0) | Keep satisfied | First/last-mile partnerships, station access, Turnpike roads (dual role). |
| ★ Via (Via Jersey City) | 3 | 4 | Supportive (+1) | Manage closely | Existing city contract plus the Waymo integration offers a cheaper per-trip AV option. |
| Port Authority of NY & NJ | 3 | 3 | Champion (+2) | Manage closely | Airport access is the high-value route for JC robotaxi trips. |
| ★ JC Dept. of Infrastructure (Dir. Andrew Kaplan) | 3 | 2 | Neutral/unknown (0) | Keep satisfied | Curb access, PUDO zones, street-design conditions, data-sharing asks. |
| NJDOT (Commissioner Priya Jain) | 3 | 2 | Neutral/unknown (0) | Keep satisfied | Co-writes the pilot's safety rules; owns state roads such as Routes 1&9 and 440 in JC. |
| JC Mayor James Solomon | 3 | 1 | Neutral/unknown (0) | Keep satisfied | Curb policy, Via contract, Council agenda, municipal lobbying in Trenton. |
| ★ Tesla (Robotaxi / Cybercab) | 2 | 4 | Champion (+2) | Keep informed | Owner grassroots lobbying; federal preemption arguments. |
| ★ Bike JC (+ Citi Bike JC / Lyft) | 2 | 2 | Neutral/unknown (0) | Monitor | Vision Zero Task Force seat; council testimony. |
| ★ Safe Streets JC (pedestrians) | 2 | 2 | Neutral/unknown (0) | Monitor | Vision Zero Task Force seat; public pressure on the Mayor and Council. |
| Gig drivers / anti-AV petitioners | 1 | 3 | Opposed (-2) | Keep informed | Public hearings and pressure on legislators before floor votes. |

★ = required stakeholder from the brief

## Influence graph

```mermaid
graph LR
  nj_mvc["NJ MVC"]
  gov_sherrill["Gov. Mikie Sherrill"]
  waymo["Waymo"]
  zwicker["Sen. Andrew Zwicker"]
  nj_transit["NJ Transit"]
  via["Via"]
  panynj["Port Authority of NY & NJ"]
  jc_doi["JC Dept. of Infrastructure"]
  njdot["NJDOT"]
  mayor_solomon["JC Mayor James Solomon"]
  tesla["Tesla"]
  bike_jc["Bike JC"]
  safe_streets_jc["Safe Streets JC"]
  av_opposition["Gig drivers / anti-AV petitioners"]
  gov_sherrill -->|"appoints"| nj_mvc
  gov_sherrill -->|"appoints"| nj_transit
  gov_sherrill -->|"appoints"| njdot
  zwicker -->|"writes pilot powers for"| nj_mvc
  nj_mvc -->|"would permit/halt"| waymo
  nj_mvc -->|"would permit/halt"| tesla
  njdot -->|"co-sets safety rules"| nj_mvc
  waymo -->|"lobbies"| zwicker
  tesla -->|"lobbies against"| zwicker
  av_opposition -->|"pressures"| zwicker
  mayor_solomon -->|"directs"| jc_doi
  mayor_solomon -->|"funds/cuts contract"| via
  jc_doi -->|"controls curb for"| waymo
  bike_jc -->|"advises (VZ Task Force)"| jc_doi
  safe_streets_jc -->|"advises (VZ Task Force)"| jc_doi
  via -->|"partner (Chandler model)"| waymo
  nj_transit -->|"contracts (MicroLink)"| via
  panynj -->|"airport testing partner"| waymo
  classDef pro fill:#d6f5d6,stroke:#2e7d32
  classDef neu fill:#eeeeee,stroke:#757575
  classDef con fill:#fbd5d5,stroke:#c62828
  class waymo,zwicker,via,panynj,tesla pro
  class nj_mvc,gov_sherrill,nj_transit,jc_doi,njdot,mayor_solomon,bike_jc,safe_streets_jc neu
  class av_opposition con
```

Green = pro-AV · grey = neutral/no position · red = opposed

## Stakeholder detail

### NJ MVC (Acting Chief Admin. Rosalie Johnson)
- **Role:** Would run the S1677/A3968 3-year AV pilot. The Chief Administrator can immediately halt any AV operator and set safety rules with NJDOT.
- **Evidence:** Johnson (ex-Colorado DMV) is Acting Chair & Chief Administrator since Jan 20, 2026; no Senate confirmation found. No public AV position found.
- **Sources:** [1](https://pub.njleg.gov/Bills/2026/S2000/1677_I1.HTM) [2](https://www.roi-nj.com/2026/01/13/politics/gov-elect-sherrill-nominates-johnson-to-be-head-of-motor-vehicle-commission/) [3](https://www.nj.gov/mvc/about/chiefadmin.htm)

### Gov. Mikie Sherrill
- **Role:** Signs or vetoes S1677/A3968. Appoints the heads of MVC, NJDOT and NJ Transit.
- **Evidence:** No public AV position found. Transport priorities: NJ Transit reliability, World Cup readiness.
- **Sources:** [1](https://njbiz.com/sherrill-kolluri-dual-nj-transit-turnpike-roles/)

### Waymo
- **Role:** Mapping Jersey City, Hoboken and the Newark Airport area with human drivers; aims to launch driverless service.
- **Evidence:** Regional policy head Matt Walsh warned the bill could keep NJ out of scope for years (delay to 2028). Waymo failed to get the safety-driver phase waived. Its lidar+radar+camera stack meets the 3-sensor mandate. Newark Airport manual testing announced Oct 22, 2025.
- **Sources:** [1](https://nj1015.com/autonomous-vehicles-waymo-pilot-program/) [2](https://www.bloomberg.com/news/articles/2025-10-22/waymo-to-test-vehicles-with-human-drivers-at-newark-airport) [3](https://www.govtech.com/transportation/new-jersey-bill-could-put-the-brakes-on-autonomous-cabs) [4](https://electrek.co/2026/07/09/new-jersey-bill-tesla-camera-robotaxi/)

### Sen. Andrew Zwicker (S1677 prime sponsor)
- **Role:** Writing the AV rules. S1677 cleared Senate Transportation 5-0 on May 11, 2026, and was referred to Budget & Appropriations. Assembly twin A3968 (Moen) was reported June 1.
- **Evidence:** Pilot design: a human-driver first phase, then driverless only if that phase is incident-free; 3 sensor types; manual controls. Says the bill is 'pro New Jersey safety', not anti-Tesla. Still in Senate Budget & Appropriations; no floor vote found.
- **Sources:** [1](https://legiscan.com/NJ/bill/S1677/2026) [2](https://newjerseymonitor.com/2026/05/13/driverless-cars-nj-senate/) [3](https://pub.njleg.gov/Bills/2026/A4000/3968_I1.HTM)

### NJ Transit (CEO Kris Kolluri)
- **Role:** Runs HBLR and buses in JC. Kolluri was kept by Gov. Sherrill and also heads the NJ Turnpike Authority. Running a MicroLink microtransit pilot with Via (launched April 6, 2026).
- **Evidence:** No public AV position found. Focus is the Rapid Action Plan and the 11% budget increase.
- **Sources:** [1](https://newjerseyglobe.com/governor/sherrill-says-kolluri-will-run-nj-transit-and-turnpike-authority/) [2](https://content.njtransit.com/sites/default/files/board/meeting_minutes/2026_04_15_OpenSess.pdf) [3](https://www.aol.com/news/via-nj-transit-partner-microtransit-202851934.html)

### Via (Via Jersey City)
- **Role:** Runs city-funded Via Jersey City (cut to Mon-Fri 6:30a-7p, $2.55 fare, from July 1, 2026). Also runs NJ Transit's MicroLink pilot.
- **Evidence:** Waymo-Via partnership (Sept 2025) puts Waymo AVs into Chandler, AZ public transit. That gives JC a ready path to AV microtransit. JC's budget gap (about $90M) is shrinking the service.
- **Sources:** [1](https://www.jerseycitynj.gov/viachanges) [2](https://gothamist.com/news/jersey-city-weighs-cutting-via-microtransit-service-amid-budget-crisis) [3](https://ridewithvia.com/news/waymo-and-via-announce-strategic-partnership-to-advance-avs-in-public-transit) [4](https://www.aol.com/news/via-nj-transit-partner-microtransit-202851934.html)

### Port Authority of NY & NJ
- **Role:** Partner for Waymo's human-driven testing at Newark Liberty Airport. Also runs PATH, the main JC-Manhattan link.
- **Evidence:** Hosted Waymo manual testing at Newark (from Oct 2025). Separately announced (Feb 25, 2026) a spring-2026 AV shuttle test at Newark with Oceaneering, Ohmio and Glydways.
- **Sources:** [1](https://www.ttnews.com/articles/waymo-test-humans-new-jersey) [2](https://www.ttnews.com/articles/nj-airport-autonomous-shuttles)

### JC Dept. of Infrastructure (Dir. Andrew Kaplan)
- **Role:** Runs traffic engineering, transportation planning and curb design, and leads the Vision Zero update. Kaplan was appointed March 2026 (succeeding Barkha Patel).
- **Evidence:** No public AV position found. Kaplan: 'zero is the only acceptable number' (traffic deaths). Controls pick-up/drop-off zones and quick-build street design.
- **Sources:** [1](https://www.jerseycitynj.gov/news/andrew_kaplan_as_infrastructure_director) [2](https://hudsoncountyview.com/solomon-names-kaplan-as-jersey-city-infrastruct-dir-cialone-to-remain-hedc-head/) [3](https://usa.streetsblog.org/2026/06/12/in-new-jersey-mayors-show-how-quickly-we-can-slow-down-drivers)

### NJDOT (Commissioner Priya Jain)
- **Role:** Consults with MVC on the pilot's safety requirements and task force under S1677/A3968. Jain was confirmed unanimously.
- **Evidence:** No public AV position found. Priorities: World Cup infrastructure, permitting reform.
- **Sources:** [1](https://www.progressiverailroading.com/people/news/Jain-nominated-as-next-NJ-DOT-commissioner--76182) [2](https://pub.njleg.gov/Bills/2026/A4000/3968_I1.HTM)

### JC Mayor James Solomon
- **Role:** Took office January 2026. Leading the Vision Zero reboot (100 quick-builds) and the Via cuts amid a budget deficit.
- **Evidence:** No public AV statement found. Safety and budget framing will decide the city's stance.
- **Sources:** [1](https://usa.streetsblog.org/2026/06/12/in-new-jersey-mayors-show-how-quickly-we-can-slow-down-drivers) [2](https://www.hobokengirl.com/jersey-city-budget-deficit-february-2026-nj/)

### Tesla (Robotaxi / Cybercab)
- **Role:** Wants Robotaxi in NJ; camera-only stack and no-pedal Cybercab would fail S1677's 3-sensor and manual-controls rules.
- **Evidence:** Urged NJ owners to lobby against S1677. No NJ service; unsupervised service is limited to TX and FL.
- **Sources:** [1](https://www.teslarati.com/tesla-urges-new-jersey-owners-to-oppose-new-bill-block-robotaxi/) [2](https://evwire.com/p/new-jersey-robotaxi-bill-tesla-cybercab) [3](https://www.planetizen.com/news/2026/07/137972-new-jersey-bill-would-require-avs-use-3-sensing-technologies-banning-teslas)

### Bike JC (+ Citi Bike JC / Lyft)
- **Role:** Bike advocacy group on the reinstated Vision Zero Task Force. Citi Bike (Lyft) runs the JC/Hoboken bike share under a new 2026 long-term contract with no city subsidy.
- **Evidence:** No public AV position found. Likely issues: AVs blocking bike lanes, and how AVs detect cyclists.
- **Sources:** [1](https://www.jerseycitynj.gov/cityhall/infrastructure/transportation_resources/visionzero) [2](https://citibikenyc.com/pricechange)

### Safe Streets JC (pedestrians)
- **Role:** Pedestrian-safety advocacy group on the Vision Zero Task Force. Gave Mayor Solomon a 10-point first-100-days plan.
- **Evidence:** No public AV position found. Its focus is traffic deaths (6 killed by vehicles on JC streets the prior year).
- **Sources:** [1](https://www.safestreetsjerseycity.org/safe-streets-jc-presents-10-point-plan-to-prioritize-safety-in-mayor-solomons-first-100-days/) [2](https://www.jerseycitynj.gov/cityhall/infrastructure/transportation_resources/visionzero)

### Gig drivers / anti-AV petitioners
- **Role:** A public petition asks the Governor to stop AV testing in NJ over rideshare and delivery job losses. No organized NJ union stance found.
- **Evidence:** Action Network petition. NY's Independent Drivers Guild opposed a similar NY proposal, so NJ labor could follow.
- **Sources:** [1](https://actionnetwork.org/petitions/stop-waymos-autonomous-vehicles-from-spreading-in-new-jersey/) [2](https://newjersey.news12.com/2026/01/21/rideshare-drivers-raise-concerns-over-robo-taxi-proposal/1rs6YhzUe3vCWPUSCIoY6A)
