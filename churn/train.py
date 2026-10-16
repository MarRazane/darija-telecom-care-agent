
from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "churn" / "artifacts"
DB_URL = os.getenv("DATABASE_URL", "postgresql://dzmobile:dzmobile@localhost:5432/dzmobile")


TRAIN_CUTOFFS = ["2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"]
VALID_CUTOFF = "2026-07-31"
TEST_CUTOFF = "2026-08-31"

ID_COLS = ["cutoff_date", "subscriber_id"]
TARGET = "churned"
CATEGORICAL = ["plan", "wilaya", "age_band"]

SEED = 42
ACTIVE_WITHIN_DAYS = 7
#Load data

def load_data(db_url: str) -> pd.DataFrame:
    query = """
        SELECT f.*, l.churned
        FROM churn_features f
        JOIN churn_labels   l USING (cutoff_date, subscriber_id)
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(query)
        columns = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=columns)

    df["cutoff_date"] = pd.to_datetime(df["cutoff_date"]).dt.strftime("%Y-%m-%d")
    numeric = [c for c in df.columns if c not in ID_COLS + CATEGORICAL]
    df[numeric] = df[numeric].apply(pd.to_numeric).astype(float)
    df[TARGET] = df[TARGET].astype(int)
    return df


def split_by_time(df: pd.DataFrame):
    df = df[df["days_since_last_usage"] <= ACTIVE_WITHIN_DAYS]
    train = df[df["cutoff_date"].isin(TRAIN_CUTOFFS)]
    valid = df[df["cutoff_date"] == VALID_CUTOFF]
    test = df[df["cutoff_date"] == TEST_CUTOFF]
    return train, valid, test


def lift_at(y_true: np.ndarray, scores: np.ndarray, top: float = 0.10):
    
    n_top = int(len(scores) * top)
    order = np.argsort(-scores)              
    top_idx = order[:n_top]
    rate_top = y_true[top_idx].mean()
    rate_all = y_true.mean()
    recall = y_true[top_idx].sum() / y_true.sum()
    return rate_top / rate_all, recall


def evaluate(name: str, y_true: np.ndarray, scores: np.ndarray) -> dict:
    lift10, recall10 = lift_at(y_true, scores, 0.10)
    return {
        "model": name,
        "rows": int(len(y_true)),
        "churn_rate": round(float(y_true.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y_true, scores)), 4),
        "pr_auc": round(float(average_precision_score(y_true, scores)), 4),
        "lift_top10": round(float(lift10), 2),
        "recall_top10": round(float(recall10), 4),
    }


def train_logistic(train: pd.DataFrame, numeric: list[str]) -> Pipeline:
   
    preprocess = ColumnTransformer([
        ("num", Pipeline([
  
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
        ]), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ])
    model = Pipeline([
        ("prep", preprocess),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    model.fit(train[numeric + CATEGORICAL], train[TARGET])
    return model
#model


def to_lgb_frame(df: pd.DataFrame, numeric: list[str]) -> pd.DataFrame:

    X = df[numeric + CATEGORICAL].copy()
    for col in CATEGORICAL:
        X[col] = pd.Categorical(X[col], categories=sorted(CATEGORICAL_VALUES[col]))
    return X


CATEGORICAL_VALUES: dict[str, set] = {}


def train_lightgbm(train: pd.DataFrame, valid: pd.DataFrame, numeric: list[str]):
    params = dict(
        objective="binary",
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=50,   
        subsample=0.8,            
        subsample_freq=1,
        colsample_bytree=0.8,     
        reg_lambda=1.0,
        n_estimators=2000,         
        random_state=SEED,
        verbose=-1,
    )
    model = lgb.LGBMClassifier(**params)
    model.fit(
        to_lgb_frame(train, numeric), train[TARGET],
        eval_set=[(to_lgb_frame(valid, numeric), valid[TARGET])],
        eval_metric="average_precision",
        
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


#main


def main():
    print("Loading features and labels from PostgreSQL...")
    df = load_data(DB_URL)
    numeric = [c for c in df.columns if c not in ID_COLS + CATEGORICAL + [TARGET]]
    for col in CATEGORICAL:
        CATEGORICAL_VALUES[col] = set(df[col].unique())

    train, valid, test = split_by_time(df)
    print(f"  {len(numeric)} numeric + {len(CATEGORICAL)} categorical features")
    for name, part in [("train", train), ("valid", valid), ("test", test)]:
        print(f"  {name:<5}: {len(part):>6,} rows, churn rate {part[TARGET].mean():.2%}")

    print("\nTraining logistic regression...")
    logit = train_logistic(train, numeric)
    logit_scores = logit.predict_proba(test[numeric + CATEGORICAL])[:, 1]

    print("Training LightGBM...")
    gbm = train_lightgbm(train, valid, numeric)
    print(f"  early stopping kept {gbm.best_iteration_} trees")
    gbm_scores = gbm.predict_proba(to_lgb_frame(test, numeric))[:, 1]

    y_test = test[TARGET].to_numpy()
    results = [
        evaluate("logistic_regression", y_test, logit_scores),
        evaluate("lightgbm", y_test, gbm_scores),
    ]

    print(f"\nTest month: cutoff {TEST_CUTOFF} (predicting September)\n")
    table = pd.DataFrame(results).set_index("model")
    print(table.to_string())

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(logit, ARTIFACTS / "logistic.joblib")
    joblib.dump({"model": gbm, "numeric": numeric, "categorical": CATEGORICAL,
                 "categories": {c: sorted(v) for c, v in CATEGORICAL_VALUES.items()}},
                ARTIFACTS / "lightgbm.joblib")
    preds = test[ID_COLS + [TARGET]].copy()
    preds["score_logistic"] = logit_scores
    preds["score_lightgbm"] = gbm_scores
    preds.to_csv(ARTIFACTS / "test_predictions.csv", index=False)
    (ARTIFACTS / "metrics.json").write_text(json.dumps(results, indent=2))
    print(f"\nSaved models, predictions and metrics to {ARTIFACTS}")


if __name__ == "__main__":
    main()