-- Interface register — interfaces
-- Single canonical table, current-state only (no revision history).
-- Generated to match src/migration_intake/persistence/models_interfaces.py
-- and the Alembic migration
-- src/migration_intake/persistence/migrations/versions/0016_interfaces_register.py.
--
-- Do not run this file directly against a shared environment — use
-- `alembic upgrade head` instead, so the revision is recorded in
-- alembic_version. This file is provided for review/reference only.

-- =====================================================================
-- Oracle
-- =====================================================================
CREATE TABLE interfaces (
    id                                    CHAR(36)      NOT NULL,
    application_id                        CHAR(36)      NOT NULL,
    intake_id                             CHAR(36),
    interface_correlation_id              VARCHAR2(255) NOT NULL,
    normalized_interface_correlation_id   VARCHAR2(255) NOT NULL,
    interface_app_acronym                 VARCHAR2(255),
    interface_system_location             VARCHAR2(255),
    data_traffic_direction                VARCHAR2(32),
    target_protocol                       VARCHAR2(255),
    future_port                           VARCHAR2(32),
    state                                 VARCHAR2(30)  DEFAULT 'ACTIVE' NOT NULL,
    origin                                VARCHAR2(16)  DEFAULT 'MANUAL' NOT NULL,
    created_at                            VARCHAR2(32)  NOT NULL,
    created_by_id                         CHAR(36)      NOT NULL,
    updated_at                            VARCHAR2(32)  NOT NULL,
    updated_by_id                         CHAR(36)      NOT NULL,
    row_version                           NUMBER(10)    NOT NULL,
    CONSTRAINT pk_interfaces PRIMARY KEY (id),
    CONSTRAINT uq_irec_app_norm UNIQUE (application_id, normalized_interface_correlation_id),
    CONSTRAINT fk_irec_appl FOREIGN KEY (application_id) REFERENCES applications (id),
    CONSTRAINT fk_irec_intk FOREIGN KEY (intake_id) REFERENCES intakes (id),
    CONSTRAINT fk_irec_cact FOREIGN KEY (created_by_id) REFERENCES actors (id),
    CONSTRAINT fk_irec_uact FOREIGN KEY (updated_by_id) REFERENCES actors (id)
);

-- =====================================================================
-- SQLite (local dev / test — types are TypeDecorator impl types, same
-- physical shapes as Oracle: CHAR(36) UUIDs, VARCHAR(32) UTC timestamps)
-- =====================================================================
-- CREATE TABLE interfaces (
--     id                                   CHAR(36)     NOT NULL,
--     application_id                       CHAR(36)     NOT NULL,
--     intake_id                            CHAR(36),
--     interface_correlation_id             VARCHAR(255) NOT NULL,
--     normalized_interface_correlation_id  VARCHAR(255) NOT NULL,
--     interface_app_acronym                VARCHAR(255),
--     interface_system_location            VARCHAR(255),
--     data_traffic_direction               VARCHAR(32),
--     target_protocol                      VARCHAR(255),
--     future_port                          VARCHAR(32),
--     state                                VARCHAR(30)  NOT NULL DEFAULT 'ACTIVE',
--     origin                               VARCHAR(16)  NOT NULL DEFAULT 'MANUAL',
--     created_at                           VARCHAR(32)  NOT NULL,
--     created_by_id                        CHAR(36)     NOT NULL,
--     updated_at                           VARCHAR(32)  NOT NULL,
--     updated_by_id                        CHAR(36)     NOT NULL,
--     row_version                          INTEGER      NOT NULL,
--     CONSTRAINT pk_interfaces PRIMARY KEY (id),
--     CONSTRAINT uq_irec_app_norm UNIQUE (application_id, normalized_interface_correlation_id),
--     CONSTRAINT fk_irec_appl FOREIGN KEY (application_id) REFERENCES applications (id),
--     CONSTRAINT fk_irec_intk FOREIGN KEY (intake_id) REFERENCES intakes (id),
--     CONSTRAINT fk_irec_cact FOREIGN KEY (created_by_id) REFERENCES actors (id),
--     CONSTRAINT fk_irec_uact FOREIGN KEY (updated_by_id) REFERENCES actors (id)
-- );
