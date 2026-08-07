# Mental Health KG — Design Notes

## Node labels
| Label | Key fields |
|-------|-----------|
| Condition | id, name, dsm_code, icd_code |
| Symptom | id, name |
| Treatment | id, name, modality |
| Medication | id, name, drug_class |
| RiskFactor | id, name |
| Population | id, name |

## Edge types
| Edge | From -> To | Meaning |
|------|-----------|---------|
| HAS_SYMPTOM | Condition -> Symptom | presenting symptoms |
| TREATED_BY | Condition -> Treatment | treatment options |
| TREATS | Treatment -> Condition | indication |
| PRESCRIBED_FOR | Medication -> Condition | pharmacological indication |
| INCREASES_RISK | RiskFactor -> Condition | risk association |
| AFFECTS | Condition -> Population | affected group |

## Data sources
List each source, license, and contribution. Fill in `{{SOURCES}}`.
Handle clinical data with appropriate care and licensing review.
