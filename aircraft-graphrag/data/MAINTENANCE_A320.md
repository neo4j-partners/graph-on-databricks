# A320-200 Maintenance and Troubleshooting Manual

**Document Number:** AMM-A320-2024-001
**Revision:** 1.0
**Effective Date:** October 1, 2024
**Applicability:** A320-200 series aircraft equipped with IAE V2500-A1 engines
**Operator:** SkyWays Airlines
**Fleet:** N30268B, N81338F, N32276J, N76758N, N63098R

---

## Document Control

| Rev | Date | Description | Author |
|-----|------|-------------|--------|
| 1.0 | 2024-10-01 | Initial Release | Engineering Division |
| 0.9 | 2024-09-15 | Draft for review | Maintenance Planning |

**NOTICE:** This manual contains proprietary information. Maintenance procedures must be performed by certified personnel only. Always refer to the latest revision of Airbus AMM documentation for authoritative guidance.

---

## Table of Contents

1. [Aircraft Overview](#1-aircraft-overview)
2. [System Architecture](#2-system-architecture)
3. [Engine System - V2500-A1](#3-engine-system---v2500-a1)
4. [Engine Troubleshooting Procedures](#4-engine-troubleshooting-procedures)
5. [Avionics System](#5-avionics-system)
6. [Hydraulics System](#6-hydraulics-system)
7. [Fault Code Reference](#7-fault-code-reference)
8. [Troubleshooting Decision Trees](#8-troubleshooting-decision-trees)
9. [Scheduled Maintenance Tasks](#9-scheduled-maintenance-tasks)
10. [Appendices](#10-appendices)

---

## 1. Aircraft Overview

### 1.1 General Specifications

| Parameter | Value |
|-----------|-------|
| Aircraft Type | Airbus A320-200 |
| Powerplant | 2x IAE V2500-A1 Turbofan |
| Maximum Takeoff Weight (MTOW) | 77,000 kg (169,756 lb) |
| Maximum Landing Weight (MLW) | 66,000 kg (145,505 lb) |
| Maximum Zero Fuel Weight (MZFW) | 62,500 kg (137,789 lb) |
| Fuel Capacity | 24,210 liters (6,396 US gal) |
| Range | 6,100 km (3,300 nm) |
| Service Ceiling | 39,800 ft |

### 1.2 Fleet Configuration

The A320-200 fleet operates across four partner carriers configured for medium-haul operations. The combined fleet of approximately 30 aircraft is distributed as follows:

| Operator | Aircraft Count | Primary Routes |
|----------|---------------|----------------|
| ExampleAir | 8 | Domestic medium-haul |
| SkyWays | 8 | Domestic medium-haul |
| RegionalCo | 7 | Mixed domestic/regional |
| NorthernJet | 7 | Domestic medium-haul |

Aircraft entered service between 2017 and 2023, configured in a single-class or dual-class layout for 150–180 passengers.

### 1.3 ATA Chapter Reference

This manual covers the following ATA chapters:

| ATA Chapter | System | Reference Section |
|-------------|--------|-------------------|
| ATA 29 | Hydraulic Power | Section 6 |
| ATA 34 | Navigation | Section 5 |
| ATA 71 | Powerplant | Sections 3-4 |
| ATA 72 | Engine | Sections 3-4 |
| ATA 73 | Engine Fuel and Control | Section 3 |
| ATA 77 | Engine Indicating | Section 3 |

---

## 2. System Architecture

### 2.1 Major System Groups

Each A320-200 aircraft comprises four primary monitored system groups:

```
AIRCRAFT (A320-200)
│
├── ENGINE SYSTEM #1 (V2500-A1 Left)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── ENGINE SYSTEM #2 (V2500-A1 Right)
│   ├── Fan Module
│   ├── Compressor Stage (High-Pressure)
│   ├── High-Pressure Turbine
│   ├── Main Fuel Pump
│   └── Thrust Bearing Assembly
│
├── AVIONICS SYSTEM
│   ├── Flight Management System (FMS)
│   ├── Air Data Computer (ADC)
│   └── Navigation Receiver (NAV)
│
└── HYDRAULICS SYSTEM
    ├── Main Hydraulic Pump
    ├── Hydraulic Reservoir
    └── Flap Actuator Assembly
```

#### 2.1.1 Engine Systems (V2500-A1)

The A320-200 is powered by two International Aero Engines (IAE) V2500-A1 high-bypass turbofan engines, mounted in underwing nacelles. Each engine produces 25,000 lbf of thrust and operates independently with full redundancy. The V2500 features a two-spool design with a single-stage fan, 4-stage low-pressure compressor, 10-stage high-pressure compressor, annular combustor, 2-stage high-pressure turbine, and 5-stage low-pressure turbine. Engine health is continuously monitored via four dedicated sensors per engine measuring exhaust gas temperature (EGT), vibration levels, fan speed (N1), and fuel flow rate. The engine systems account for approximately 58% of all maintenance events in the fleet, with the most common issues being overheat conditions, vibration exceedances, and bearing wear.

**ATA Reference:** Chapters 71 (Powerplant), 72 (Engine), 73 (Engine Fuel and Control), 77 (Engine Indicating)

#### 2.1.2 Avionics System

The avionics system provides flight management, navigation, and air data computation functions essential for safe aircraft operation. The system is built around dual Flight Management Systems (FMS) that handle flight planning, navigation computation, performance optimization, and guidance commands. Three Air Data Computers (ADC) provide redundant altitude, airspeed, and Mach number calculations using pitot-static inputs. The Navigation Receiver integrates VOR, ILS localizer, glideslope, and marker beacon reception for precision approaches. All avionics components communicate via ARINC 429 digital data buses with built-in test equipment (BITE) for fault detection. Avionics-related maintenance events comprise approximately 22% of fleet issues, primarily involving sensor drift and electrical faults that are often resolved through software patches or calibration adjustments.

**ATA Reference:** Chapter 34 (Navigation)

#### 2.1.3 Hydraulics System

The A320-200 hydraulic system provides power for flight control surfaces, landing gear operation, brakes, thrust reversers, and cargo doors. The aircraft employs three independent hydraulic systems designated Green, Blue, and Yellow, each operating at 3,000 psi. This manual focuses on the Green system, which is powered by an engine-driven pump on Engine #1. The system includes a main hydraulic pump capable of 26 gpm flow rate, a 14.5-liter reservoir with integrated quantity indication, and multiple actuators including the flap actuator assembly for high-lift device operation. Hydraulic fluid (Skydrol LD-4) requires regular monitoring for contamination and proper fluid levels. The hydraulics system represents approximately 19% of maintenance events, with leaks and fluid contamination being the most common issues requiring attention.

**ATA Reference:** Chapter 29 (Hydraulic Power)

### 2.2 Engine Health Monitoring

Each V2500 engine is equipped with four primary monitoring sensors:

| Sensor Type | Parameter | Unit | Location |
|-------------|-----------|------|----------|
| EGT | Exhaust Gas Temperature | °C | Turbine exhaust |
| VIB | Engine Vibration | ips (inches/sec) | Fan case |
| N1Speed | Fan Speed | % RPM | Fan shaft |
| FuelFlow | Fuel Flow | kg/s | Fuel metering unit |

**Sensor Sampling Rate:** Continuous (1 Hz during flight, recorded hourly for trend analysis)

**Digital Twin Monitoring Note:** The Digital Twin Monitoring System records hourly trend-averaged EGT values on a normalized scale calibrated for long-term degradation detection. These trend values (nominal baseline ~645°C, warning threshold ~674°C) differ from the instantaneous ECAM EGT readings shown in Section 3.3 and Appendix 10.1, which reflect peak values during takeoff and high-power operations. The trend-monitoring scale is used to detect gradual EGT margin deterioration over weeks and months rather than acute exceedances. Note: the digital twin dataset models this A320-200 variant as equipped with CFM56-5B engines; procedure steps in this manual reference the IAE V2500-A1 alternative powerplant.

### 2.3 Component Identification Schema

Components are identified using the following nomenclature:

```
[Aircraft ID]-[System]-[Component]

Example: AC1002-S01-C03
         │       │    └── Component: High-Pressure Turbine
         │       └─────── System: Engine #1
         └─────────────── Aircraft: AC1002 (N30268B)
```

**System Codes:**
- S01: Engine #1 (Left)
- S02: Engine #2 (Right)
- S03: Avionics Suite
- S04: Hydraulics System

---

## 3. Engine System - V2500-A1

### 3.1 Engine Specifications

| Parameter | Value |
|-----------|-------|
| Manufacturer | International Aero Engines (IAE) |
| Model | V2500-A1 |
| Type | Two-spool turbofan |
| Thrust Rating | 25,000 lbf (111 kN) |
| Bypass Ratio | 5.4:1 |
| Overall Pressure Ratio | 30:1 |
| Dry Weight | 2,359 kg (5,200 lb) |

### 3.2 Component Descriptions

#### 3.2.1 Fan Module
**Part Number:** V25-FM-2100
**ATA Reference:** 72-21

The fan module consists of a single-stage fan with 22 wide-chord titanium blades. The fan provides approximately 80% of total engine thrust.

**Inspection Intervals:**
- Visual inspection: Every 500 flight hours
- Borescope inspection: Every 2,500 flight hours
- Overhaul: On-condition (typically 15,000-20,000 cycles)

#### 3.2.2 Compressor Stage (High-Pressure)
**Part Number:** V25-HPC-3400
**ATA Reference:** 72-34

The 10-stage high-pressure compressor (HPC) achieves a pressure ratio of approximately 10:1. Variable stator vanes in stages 1-4 provide surge protection during transient operations.

**Common Fault Modes:**
- Compressor stall (vibration exceedance)
- Blade erosion (performance degradation)
- Variable vane actuator malfunction (sensor drift)

#### 3.2.3 High-Pressure Turbine
**Part Number:** V25-HPT-4200
**ATA Reference:** 72-42

The two-stage HPT extracts energy to drive the HPC. Turbine blades feature advanced cooling passages and thermal barrier coatings.

**Operating Limits:**
| Parameter | Normal | Caution | Maximum |
|-----------|--------|---------|---------|
| EGT (Takeoff) | < 650°C | 650-680°C | 695°C |
| EGT (Continuous) | < 620°C | 620-650°C | 665°C |

#### 3.2.4 Main Fuel Pump
**Part Number:** V25-FP-7310
**ATA Reference:** 73-10

The engine-driven fuel pump provides metered fuel flow to the combustion chamber. The pump incorporates an integral fuel filter and fuel-oil heat exchanger.

**Flow Rate:** 0.85 - 1.95 kg/s (normal operating range)

**Warning Signs of Degradation:**
- Fluctuating fuel flow readings
- Increased fuel filter differential pressure
- Abnormal pump vibration

#### 3.2.5 Thrust Bearing Assembly
**Part Number:** V25-TB-7250
**ATA Reference:** 72-50

The thrust bearing assembly absorbs axial loads from the high-pressure rotor system. Ball bearing design with oil jet lubrication.

**Replacement Criteria:**
- Oil debris analysis exceeding limits
- Bearing temperature rise > 15°C above baseline
- Audible bearing noise during ground run

### 3.3 Normal Operating Parameters

| Parameter | Idle | Cruise | Takeoff |
|-----------|------|--------|---------|
| N1Speed (% RPM) | 22-28% | 85-92% | 100-104% |
| N2 (% RPM) | 58-65% | 92-97% | 100-102% |
| EGT (°C) | 380-450 | 520-580 | 620-680 |
| FuelFlow (kg/s) | 0.15-0.25 | 0.65-0.85 | 1.20-1.95 |
| Vibration (ips) | < 0.8 | < 1.2 | < 2.0 |

---

## 4. Engine Troubleshooting Procedures

### 4.1 Overheat Condition (EGT Exceedance)

**Fault Code:** ENG-OVH-001
**Severity Classification:** CRITICAL / MAJOR / MINOR (based on temperature and duration)

#### Symptoms
- EGT indication above normal operating range
- ECAM caution/warning message
- Possible visible heat damage on borescope inspection

#### Immediate Actions
1. Reduce thrust to idle if flight conditions permit
2. Monitor EGT trend for stabilization
3. If EGT exceeds 695°C, initiate engine shutdown procedures per QRH

#### Troubleshooting Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Review DFDR/QAR data for EGT exceedance duration | Document peak temperature and exposure time |
| 2 | Perform visual inspection of exhaust nozzle | Check for discoloration or distortion |
| 3 | Borescope inspection of HPT blades | Check for thermal distress, coating loss |
| 4 | Verify EGT probe calibration | Compare dual probe readings (< 5°C variance) |
| 5 | Check fuel nozzle spray pattern | Ensure even fuel distribution |

#### Corrective Actions by Severity

**CRITICAL (EGT > 695°C or duration > 5 minutes above 680°C):**
- Ground aircraft pending HPT borescope inspection
- If blade damage found: Engine removal for shop visit
- Estimated downtime: 5-10 days

**MAJOR (EGT 650-680°C, intermittent):**
- Perform hot section inspection within 50 flight hours
- Replace EGT probes if calibration drift detected
- Monitor trend data for recurrence

**MINOR (EGT trending high but within limits):**
- Adjust engine trim if applicable
- Schedule inspection at next C-check
- Continue monitoring with increased frequency

### 4.2 Vibration Exceedance

**Fault Code:** ENG-VIB-002
**Severity Classification:** CRITICAL / MAJOR / MINOR

#### Vibration Limits

| Level | N1 Vibration | N2 Vibration | Action Required |
|-------|--------------|--------------|-----------------|
| Normal | < 2.0 ips | < 1.5 ips | Continue operations |
| Caution | 2.0-3.5 ips | 1.5-2.5 ips | Increase monitoring |
| Warning | 3.5-5.0 ips | 2.5-4.0 ips | Return to base |
| Limit | > 5.0 ips | > 4.0 ips | Shutdown engine |

#### Troubleshooting Procedure

| Step | Action | Diagnostic Indicator |
|------|--------|---------------------|
| 1 | Identify vibration frequency spectrum | Isolate rotor source (N1 vs N2) |
| 2 | Check fan blade condition | FOD damage, ice accretion, blade loss |
| 3 | Inspect spinner and nosecone | Balance weights, attachment |
| 4 | Review oil debris analysis | Bearing wear indication |
| 5 | Perform fan blade balance check | Correct imbalance if identified |

#### Common Root Causes
- Fan blade damage from FOD (40% of cases)
- Bearing wear in thrust bearing assembly (25%)
- Compressor blade erosion (20%)
- Sensor malfunction / cable damage (15%)

### 4.3 Fuel Starvation

**Fault Code:** ENG-FUEL-003
**Severity Classification:** CRITICAL / MAJOR

#### Symptoms
- Fuel flow fluctuation or sudden drop
- Engine rollback or flameout
- Fuel filter bypass indication

#### Immediate Actions
1. Check fuel quantity and crossfeed configuration
2. Select alternate fuel pump if available
3. If flameout occurs, initiate relight procedure per QRH

#### Troubleshooting Procedure

| Step | Action | Check Point |
|------|--------|-------------|
| 1 | Verify fuel tank quantity | Ensure adequate fuel and no fuel imbalance |
| 2 | Check fuel filter differential pressure | Replace if > 15 psi differential |
| 3 | Inspect fuel pump delivery pressure | Nominal: 800-1200 psi |
| 4 | Check fuel metering unit operation | Verify proper scheduling |
| 5 | Inspect fuel lines for leaks or blockage | Visual and pressure decay test |

### 4.4 Bearing Wear

**Fault Code:** ENG-BRG-004
**Severity Classification:** CRITICAL / MAJOR / MINOR

#### Detection Methods
- Oil debris monitoring (chip detectors, spectrographic analysis)
- Vibration trend analysis
- Oil consumption monitoring
- Temperature rise in bearing compartment

#### Oil Analysis Limits

| Metal | Normal (ppm) | Caution (ppm) | Action (ppm) |
|-------|--------------|---------------|--------------|
| Iron (Fe) | < 5 | 5-15 | > 15 |
| Chromium (Cr) | < 2 | 2-5 | > 5 |
| Nickel (Ni) | < 3 | 3-8 | > 8 |
| Silver (Ag) | < 1 | 1-3 | > 3 |

#### Corrective Actions
- **CRITICAL:** Immediate engine removal; bearing replacement at shop
- **MAJOR:** Schedule engine removal within 100 flight hours
- **MINOR:** Increase oil sampling frequency to every 50 hours; trend monitoring

---

## 5. Avionics System

### 5.1 System Overview

The A320-200 avionics suite provides flight management, navigation, and air data functions integrated through the ARINC 429 digital data bus.

### 5.2 Component Descriptions

#### 5.2.1 Flight Management System (FMS)
**Part Number:** AVN-FMS-3401
**ATA Reference:** 34-01

The dual FMS units provide:
- Flight planning and navigation
- Performance optimization
- Automated guidance commands
- ACARS datalink interface

**Common Faults:**
- Database corruption (requires reload)
- Navigation sensor input failures
- Display unit anomalies

#### 5.2.2 Air Data Computer (ADC)
**Part Number:** AVN-ADC-3402
**ATA Reference:** 34-02

Three ADCs provide:
- Altitude computation
- Airspeed calculation
- Mach number derivation
- Total air temperature

**Calibration Requirements:**
- Leak test: Every 24 months
- Accuracy verification: Every 12 months

#### 5.2.3 Navigation Receiver (NAV)
**Part Number:** AVN-NAV-3403
**ATA Reference:** 34-03

Integrated VOR/ILS receiver providing:
- VOR bearing information
- Localizer guidance
- Glideslope guidance
- Marker beacon reception

### 5.3 Avionics Troubleshooting

#### 5.3.1 Sensor Drift

**Fault Code:** AVN-SDR-001

Sensor drift manifests as gradual deviation between redundant sensor inputs or comparison with known references.

**Diagnostic Steps:**
1. Compare ADC outputs (ADC1 vs ADC2 vs ADC3)
2. Cross-check with GPS-derived parameters
3. Review BITE (Built-In Test Equipment) fault logs
4. Perform sensor calibration verification

**Corrective Actions:**
- Software recalibration if within tolerance
- ADC replacement if drift exceeds 2% of full scale
- Wiring inspection for intermittent connections

#### 5.3.2 Electrical Fault

**Fault Code:** AVN-ELF-002

**Common Causes:**
- Power supply irregularities
- Ground faults
- Connector corrosion
- Wire chafing

**Isolation Procedure:**
1. Check circuit breaker status
2. Measure bus voltage at LRU
3. Inspect connectors for damage/corrosion
4. Perform continuity test on suspect wiring
5. Apply software patch if fault is software-related

---

## 6. Hydraulics System

### 6.1 System Overview

The A320-200 hydraulic system operates at 3,000 psi and comprises three independent systems (Green, Blue, Yellow). This section focuses on the Green system components.

### 6.2 Component Descriptions

#### 6.2.1 Main Hydraulic Pump
**Part Number:** HYD-PUMP-2901
**ATA Reference:** 29-01

Engine-driven pump specifications:
- Operating pressure: 3,000 psi
- Flow rate: 26 gpm (at 3,000 psi)
- Case drain flow: < 3 gpm

#### 6.2.2 Hydraulic Reservoir
**Part Number:** HYD-RES-2902
**ATA Reference:** 29-02

- Capacity: 14.5 liters (Green system)
- Operating temperature: -54°C to +135°C
- Fluid type: Skydrol LD-4 or equivalent

#### 6.2.3 Flap Actuator Assembly
**Part Number:** HYD-FLAP-2903
**ATA Reference:** 29-03

Linear hydraulic actuator providing:
- Flap extension/retraction
- Position feedback to SFCC
- Load limiting protection

### 6.3 Hydraulics Troubleshooting

#### 6.3.1 Leak Detection

**Fault Code:** HYD-LEAK-001

**Inspection Points:**
| Location | Access Panel | Common Leak Source |
|----------|--------------|-------------------|
| Pump area | 161VU | Pump seal, case drain |
| Reservoir | 162VU | Filler cap, sight glass |
| Actuators | Wing panels | Rod seals, fittings |
| Lines | Various | B-nut connections |

**Leak Classification:**
- Class A (Seep): < 1 drop/minute - Monitor
- Class B (Leak): 1-5 drops/minute - Repair within 10 days
- Class C (Heavy): > 5 drops/minute - Repair before flight

#### 6.3.2 Contamination

**Fault Code:** HYD-CNT-002

**Contamination Sources:**
- Water ingress (humidity, rain)
- Particulate matter (wear debris, external)
- Chemical contamination (wrong fluid type)

**Testing Procedure:**
1. Obtain fluid sample from reservoir drain
2. Perform particle count analysis (NAS 1638 Class 6 max)
3. Check water content (< 0.1% by volume)
4. Verify fluid acidity (TAN < 1.5)

**Corrective Actions:**
- Flush and filter if particle count elevated
- Replace fluid if water or chemical contamination
- Inspect and clean reservoir if debris source identified

---

## 7. Fault Code Reference

### 7.1 Engine Fault Codes

| Code | Description | Severity | ATA | Immediate Action |
|------|-------------|----------|-----|------------------|
| ENG-OVH-001 | EGT Overheat | CRIT/MAJ/MIN | 72 | Reduce thrust, monitor |
| ENG-VIB-002 | Vibration Exceedance | CRIT/MAJ/MIN | 72 | Check limits, possible shutdown |
| ENG-FUEL-003 | Fuel Starvation | CRIT/MAJ | 73 | Check fuel config, crossfeed |
| ENG-BRG-004 | Bearing Wear | CRIT/MAJ/MIN | 72 | Oil analysis, trend monitoring |
| ENG-SDR-005 | Sensor Drift | MAJ/MIN | 77 | Cross-check redundant sensors |
| ENG-ELF-006 | Electrical Fault | CRIT/MAJ | 72 | Isolate circuit, check BITE |
| ENG-CNT-007 | Contamination | CRIT/MAJ | 72 | Borescope, oil analysis |
| ENG-LK-008 | Fuel/Oil Leak | CRIT/MAJ/MIN | 73 | Identify source, assess severity |

### 7.2 Avionics Fault Codes

| Code | Description | Severity | ATA | Immediate Action |
|------|-------------|----------|-----|------------------|
| AVN-SDR-001 | Sensor Drift | MAJ/MIN | 34 | Compare redundant units |
| AVN-ELF-002 | Electrical Fault | CRIT/MAJ | 34 | Check power supply, BITE |
| AVN-FMS-003 | FMS Malfunction | MAJ | 34 | Reset, reload database |
| AVN-ADC-004 | ADC Disagreement | MAJ | 34 | Cross-check, isolate faulty unit |
| AVN-NAV-005 | NAV Receiver Fault | MIN | 34 | Check antenna, verify tuning |

### 7.3 Hydraulics Fault Codes

| Code | Description | Severity | ATA | Immediate Action |
|------|-------------|----------|-----|------------------|
| HYD-LEAK-001 | System Leak | CRIT/MAJ/MIN | 29 | Identify source, classify severity |
| HYD-CNT-002 | Fluid Contamination | MAJ/MIN | 29 | Sample analysis |
| HYD-PRS-003 | Low Pressure | CRIT/MAJ | 29 | Check pump, reservoir level |
| HYD-ACT-004 | Actuator Malfunction | MAJ | 29 | Check position feedback |
| HYD-PUMP-005 | Pump Failure | CRIT | 29 | Alternate system selection |

### 7.4 Severity Definitions

| Level | Definition | Response Time | Flight Impact |
|-------|------------|---------------|---------------|
| CRITICAL | Safety of flight affected | Immediate | Ground aircraft |
| MAJOR | Significant system degradation | 24-72 hours | May affect dispatch |
| MINOR | Limited impact on operations | Next scheduled maintenance | No dispatch impact |

---

## 8. Troubleshooting Decision Trees

### 8.1 Engine Vibration Diagnostic Flow

```
START: Vibration Warning Received
│
├─► Is vibration > 5.0 ips (N1) or > 4.0 ips (N2)?
│   │
│   ├─► YES: Shutdown engine per QRH
│   │        Ground aircraft
│   │        Perform borescope inspection
│   │        └─► END: Major maintenance required
│   │
│   └─► NO: Continue to next step
│
├─► Is vibration > 3.5 ips (N1) or > 2.5 ips (N2)?
│   │
│   ├─► YES: Plan return to base at earliest opportunity
│   │        Do not cycle thrust unnecessarily
│   │        └─► Proceed to ground troubleshooting
│   │
│   └─► NO: Monitor and continue flight
│            Increase trend monitoring frequency
│
GROUND TROUBLESHOOTING:
│
├─► Perform visual inspection of fan blades
│   │
│   ├─► Damage found: Assess per SRM limits
│   │                 Repair or replace as required
│   │                 └─► END: Fan repair
│   │
│   └─► No damage: Continue
│
├─► Check fan blade balance
│   │
│   ├─► Imbalance detected: Perform fan balance per AMM
│   │                       └─► END: Retest
│   │
│   └─► Balance OK: Continue
│
├─► Review oil debris analysis
│   │
│   ├─► Elevated metals: Bearing wear indicated
│   │                    Schedule engine removal
│   │                    └─► END: Bearing replacement
│   │
│   └─► Normal: Continue
│
└─► Check vibration sensor and wiring
    │
    ├─► Fault found: Repair wiring or replace sensor
    │                └─► END: Sensor repair
    │
    └─► No fault: Document as intermittent
                  Continue monitoring
                  └─► END: Trend analysis
```

### 8.2 Sensor Anomaly Investigation

```
START: Sensor Reading Abnormal
│
├─► Compare with redundant sensor(s)
│   │
│   ├─► Other sensors agree (single sensor fault)
│   │   │
│   │   ├─► Check sensor wiring continuity
│   │   ├─► Verify sensor calibration
│   │   ├─► Inspect connector condition
│   │   └─► Replace sensor if faulty
│   │        └─► END: Single sensor repair
│   │
│   └─► Multiple sensors disagree
│       │
│       └─► Actual system anomaly likely
│           Investigate underlying system
│           └─► See appropriate system troubleshooting
│
└─► Is drift gradual or sudden?
    │
    ├─► Gradual: Calibration drift
    │            Schedule recalibration
    │            Monitor for trend
    │
    └─► Sudden: Likely component failure
               Immediate replacement required
```

### 8.3 Hydraulic Pressure Loss Procedure

```
START: Low Hydraulic Pressure Warning
│
├─► Check reservoir fluid level
│   │
│   ├─► LOW: Leak likely
│   │        Do not operate affected flight controls
│   │        └─► Proceed to leak isolation
│   │
│   └─► NORMAL: Continue
│
├─► Check pump operation
│   │
│   ├─► Pump running, no output: Internal pump failure
│   │                            Replace pump
│   │                            └─► END: Pump replacement
│   │
│   └─► Pump not running: Check drive system
│                         Verify N2 speed adequate
│                         Check pump clutch/coupling
│
├─► LEAK ISOLATION:
│   │
│   ├─► Pressurize system on ground
│   ├─► Systematically isolate sections
│   ├─► Visual inspection of all lines and components
│   │
│   └─► Leak found: Classify severity
│                   Repair per Class A/B/C procedures
│                   └─► END: Leak repair
│
└─► No leak found: Check pressure transducer
                   Verify gauge calibration
                   └─► END: Sensor verification
```

---

## 9. Scheduled Maintenance Tasks

### 9.1 Engine Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fan blade visual inspection | 500 FH | 1.0 hr | 1 mechanic |
| Borescope - HPT | 2,500 FH | 3.0 hr | 1 specialist |
| Borescope - Combustor | 2,500 FH | 2.5 hr | 1 specialist |
| Oil system service | 100 FH | 0.5 hr | 1 mechanic |
| Oil filter change | 600 FH | 1.0 hr | 1 mechanic |
| Fuel filter inspection | 600 FH | 1.0 hr | 1 mechanic |
| Engine mount inspection | A-check | 2.0 hr | 2 mechanics |
| Thrust reverser rigging | C-check | 8.0 hr | 2 mechanics |

### 9.2 Avionics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| FMS database update | 28 days | 0.5 hr | 1 technician |
| ADC leak test | 24 months | 2.0 hr | 1 technician |
| NAV receiver test | 12 months | 1.5 hr | 1 technician |
| Pitot-static system test | 24 months | 4.0 hr | 1 technician |
| BITE self-test review | Weekly | 0.5 hr | 1 technician |

### 9.3 Hydraulics Inspection Schedule

| Task | Interval | Duration | Personnel |
|------|----------|----------|-----------|
| Fluid level check | Daily | 0.25 hr | 1 mechanic |
| Fluid sampling | 600 FH | 0.5 hr | 1 mechanic |
| Filter change | 1,200 FH | 1.5 hr | 1 mechanic |
| Pump inspection | A-check | 2.0 hr | 1 mechanic |
| Actuator rigging check | C-check | 4.0 hr | 2 mechanics |
| System pressure test | 24 months | 3.0 hr | 2 mechanics |

### 9.4 Common Task Cards

#### Task Card: ENG-TC-001 - Engine Oil Sample

**Purpose:** Obtain oil sample for spectrographic analysis

**Tools Required:**
- Sample bottle (clean, dry)
- Drain hose adapter (P/N: V25-TOOL-001)
- Gloves and safety glasses

**Procedure:**
1. Ensure engine has been shut down for minimum 30 minutes
2. Open cowling access panel 54
3. Connect drain hose to sample port
4. Obtain 100ml sample in clean bottle
5. Cap and label sample (aircraft reg, engine position, date, hours)
6. Send to approved laboratory within 24 hours

**Completion:** Sign off in aircraft technical log

#### Task Card: HYD-TC-001 - Hydraulic Fluid Level Check

**Purpose:** Verify adequate fluid level for dispatch

**Reference:** AMM 29-11-00

**Procedure:**
1. Ensure all hydraulic systems depressurized
2. Check sight glass on each reservoir
3. Level should be between MIN and MAX marks
4. If low, replenish with approved fluid only
5. Document quantity added in tech log

---

## 10. Appendices

### 10.1 Quick Reference - Normal Operating Limits

#### Engine Parameters (V2500-A1)

| Parameter | Ground Idle | Flight Idle | Max Continuous | Takeoff |
|-----------|-------------|-------------|----------------|---------|
| N1Speed (%) | 22 | 28 | 97 | 104 |
| N2 (%) | 58 | 65 | 97 | 102 |
| EGT (°C) | 380 | 450 | 620 | 680 |
| Oil Pressure (psi) | 25-55 | 40-65 | 40-65 | 40-65 |
| Oil Temp (°C) | 40-90 | 60-120 | 60-150 | 60-155 |
| Vibration (ips) | < 1.0 | < 1.5 | < 2.5 | < 3.0 |

#### Hydraulic System

| Parameter | Normal | Warning |
|-----------|--------|---------|
| System Pressure | 2,900-3,100 psi | < 2,500 psi |
| Reservoir Level | 70-100% | < 50% |
| Fluid Temperature | -40 to +100°C | > 110°C |

### 10.2 Abbreviations and Acronyms

| Abbreviation | Definition |
|--------------|------------|
| ADC | Air Data Computer |
| AMM | Aircraft Maintenance Manual |
| ATA | Air Transport Association |
| BITE | Built-In Test Equipment |
| DFDR | Digital Flight Data Recorder |
| ECAM | Electronic Centralized Aircraft Monitor |
| EGT | Exhaust Gas Temperature |
| FH | Flight Hours |
| FMS | Flight Management System |
| FOD | Foreign Object Damage |
| HPC | High Pressure Compressor |
| HPT | High Pressure Turbine |
| IAE | International Aero Engines |
| LRU | Line Replaceable Unit |
| NAV | Navigation |
| QAR | Quick Access Recorder |
| QRH | Quick Reference Handbook |
| SFCC | Slat/Flap Control Computer |
| SRM | Structural Repair Manual |
| TAN | Total Acid Number |

### 10.3 Reference Documents

| Document | Number | Description |
|----------|--------|-------------|
| Aircraft Maintenance Manual | AMM A320 | Primary maintenance reference |
| Fault Isolation Manual | FIM A320 | Troubleshooting procedures |
| Illustrated Parts Catalog | IPC A320 | Parts identification |
| Component Maintenance Manual | CMM V2500 | Engine overhaul procedures |
| Service Bulletin Index | SB A320 | Modification status |
| Airworthiness Directives | AD List | Mandatory compliance items |

### 10.4 Emergency Contacts

| Function | Contact | Availability |
|----------|---------|--------------|
| AOG Desk | +1-800-555-0199 | 24/7 |
| Engine Manufacturer (IAE) | +1-860-555-0123 | Business hours |
| Technical Records | tech.records@skyways.aero | 24/7 |
| Engineering Support | engineering@skyways.aero | 24/7 |
| Parts Supply | parts@skyways.aero | 24/7 |

### 10.5 Fleet Maintenance Statistics Summary

Based on fleet data analysis (July – September 2024):

| Metric | Value |
|--------|-------|
| Total Maintenance Events | 277 |
| Critical Events | 144 (52%) |
| Major Events | 86 (31%) |
| Minor Events | 47 (17%) |
| Engine-Related | 161 (58%) |
| Avionics-Related | 61 (22%) |
| Hydraulics-Related | 55 (20%) |

**Top Fault Types:**
1. Overheat (EGT exceedance) — 75 events (27%)
2. Bearing wear — 63 events (23%)
3. Vibration exceedance — 53 events (19%)
4. Sensor drift — 39 events (14%)
5. Contamination — 28 events (10%)
6. Leak — 19 events (7%)

**Corrective Action Distribution:**
1. Inspected and cleared — 72 (26%)
2. Replaced component — 69 (25%)
3. Cleaned and reassembled — 61 (22%)
4. Software patch applied — 47 (17%)
5. Adjusted tolerance — 28 (10%)

### 10.6 Revision History Log

| Page | Rev | Date | Change Description |
|------|-----|------|--------------------|
| All | 1.0 | 2024-10-01 | Initial release |

---

**END OF DOCUMENT**

*This manual is for demonstration purposes. Always refer to official Airbus documentation for actual maintenance procedures.*
