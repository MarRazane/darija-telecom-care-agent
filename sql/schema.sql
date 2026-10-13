DROP TABLE IF EXISTS daily_usage;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS recharges;
DROP TABLE IF EXISTS offers;
DROP TABLE IF EXISTS subscribers;

CREATE TABLE subscribers (
    subscriber_id   INTEGER PRIMARY KEY,
    phone           VARCHAR(10) NOT NULL UNIQUE,  -- fake "09" numbers, never real ones
    signup_date     DATE        NOT NULL,
    wilaya          VARCHAR(40) NOT NULL,
    plan            VARCHAR(40) NOT NULL,         -- tariff plan (all prepaid)
    age_band        VARCHAR(10) NOT NULL
);

CREATE TABLE offers (
    offer_id        INTEGER PRIMARY KEY,
    name            VARCHAR(40) NOT NULL,
    price_dzd       INTEGER     NOT NULL CHECK (price_dzd > 0),
    data_mb         INTEGER     NOT NULL,
    minutes         INTEGER     NOT NULL,
    validity_days   INTEGER     NOT NULL,
    night_only      BOOLEAN     NOT NULL DEFAULT FALSE,
    target_segment  VARCHAR(40)                    -- marketing note, not used by models
);

CREATE TABLE recharges (
    recharge_id     BIGINT PRIMARY KEY,
    subscriber_id   INTEGER     NOT NULL REFERENCES subscribers(subscriber_id),
    recharge_date   DATE        NOT NULL,
    amount_dzd      INTEGER     NOT NULL CHECK (amount_dzd > 0),
    channel         VARCHAR(20) NOT NULL
);

CREATE TABLE subscriptions (
    subscription_id BIGINT PRIMARY KEY,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(subscriber_id),
    offer_id        INTEGER NOT NULL REFERENCES offers(offer_id),
    purchase_date   DATE    NOT NULL,
    expiry_date     DATE    NOT NULL,
    price_dzd       INTEGER NOT NULL
);

CREATE TABLE daily_usage (
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(subscriber_id),
    usage_date      DATE    NOT NULL,
    data_mb         NUMERIC(10,1) NOT NULL,
    data_mb_night   NUMERIC(10,1) NOT NULL,   
    call_minutes    NUMERIC(8,1)  NOT NULL,
    sms_count       INTEGER       NOT NULL,
    dropped_calls   INTEGER       NOT NULL,   
    PRIMARY KEY (subscriber_id, usage_date)
);

CREATE INDEX idx_recharges_sub_date     ON recharges (subscriber_id, recharge_date);
CREATE INDEX idx_subscriptions_sub_date ON subscriptions (subscriber_id, purchase_date);
CREATE INDEX idx_usage_date             ON daily_usage (usage_date);


