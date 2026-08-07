// Mental Health Knowledge Graph — schema
// Node labels: Condition, Symptom, Treatment, Medication, RiskFactor, Population
// Edge types:  HAS_SYMPTOM, TREATED_BY, TREATS, PRESCRIBED_FOR, INCREASES_RISK, AFFECTS

CREATE CONSTRAINT condition_id  IF NOT EXISTS FOR (c:Condition)   REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT symptom_id    IF NOT EXISTS FOR (s:Symptom)     REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT treatment_id  IF NOT EXISTS FOR (t:Treatment)   REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT medication_id IF NOT EXISTS FOR (m:Medication)  REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT riskfactor_id IF NOT EXISTS FOR (rf:RiskFactor) REQUIRE rf.id IS UNIQUE;
CREATE CONSTRAINT population_id IF NOT EXISTS FOR (p:Population)  REQUIRE p.id IS UNIQUE;

// (:Condition)-[:HAS_SYMPTOM]->(:Symptom)
// (:Condition)-[:TREATED_BY]->(:Treatment)
// (:Treatment)-[:TREATS]->(:Condition)
// (:Medication)-[:PRESCRIBED_FOR]->(:Condition)
// (:RiskFactor)-[:INCREASES_RISK]->(:Condition)
// (:Condition)-[:AFFECTS]->(:Population)
