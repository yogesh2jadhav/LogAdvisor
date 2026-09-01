-- Track whether a project is Java+Spark or plain Java, so reports regenerated
-- from the DB score the right set of categories.

ALTER TABLE projects ADD COLUMN project_type TEXT DEFAULT 'java-spark';
