package com.example.pipeline;

import org.apache.spark.sql.Dataset;
import org.apache.spark.sql.Row;
import org.apache.spark.sql.SparkSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Sample Spark pipeline used as an advisor test fixture.
 * Contains a join, a filter and a parquet write with weak logging,
 * plus a catch block with no error logging.
 */
public class PatientProcessor {

    private static final Logger logger = LoggerFactory.getLogger(PatientProcessor.class);

    public Dataset<Row> processPatients(SparkSession spark, String encountersPath) {
        logger.info("Starting patient processing");

        Dataset<Row> patients = spark.read().parquet("/data/patients");
        Dataset<Row> encounters = spark.read().format("parquet").load(encountersPath);

        Dataset<Row> active = patients.filter(patients.col("status").equalTo("ACTIVE"));

        Dataset<Row> joined = active.join(encounters,
                active.col("patient_id").equalTo(encounters.col("patient_id")),
                "inner");

        Dataset<Row> result = joined.select("patient_id", "encounter_id", "status");

        try {
            result.write().mode("overwrite").parquet("/data/output/active_encounters");
        } catch (Exception e) {
            // swallowed - advisor should flag missing error logging
            result = active;
        }

        return result;
    }

    public long countRecords(Dataset<Row> df) {
        return df.count();
    }
}
