package com.example.pipeline;

import org.apache.spark.sql.Dataset;
import org.apache.spark.sql.Row;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class AggregationJob {

    private static final Logger log = LoggerFactory.getLogger(AggregationJob.class);

    public Dataset<Row> summarize(Dataset<Row> encounters) {
        Dataset<Row> deduped = encounters.dropDuplicates("encounter_id");

        Dataset<Row> summary = deduped.groupBy("department").agg(
                org.apache.spark.sql.functions.count("encounter_id").alias("n"));

        try {
            summary.count();
        } catch (RuntimeException ex) {
            log.error("Aggregation failed stage={} error={}", "summarize", ex.toString());
            throw ex;
        }
        return summary;
    }

    public Dataset<Row> rename(Dataset<Row> df) {
        return df.withColumnRenamed("n", "count");
    }
}
