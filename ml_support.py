"""Explainable classroom ML demo; synthetic labels are not real outcome evidence."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["attendance_pct", "mst1_pct", "assignment_pct"]
SEED = 42


def build_model():
    rng = np.random.default_rng(SEED)
    n = 1200
    x = np.column_stack([
        rng.uniform(35, 100, n),
        rng.uniform(0, 100, n),
        rng.uniform(0, 100, n),
    ])
    risk_score = 0.40 * (1 - x[:, 0] / 100) + 0.40 * (1 - x[:, 1] / 100) + 0.20 * (1 - x[:, 2] / 100)
    y = (risk_score > 0.48).astype(int)
    flip = rng.random(n) < 0.08
    y[flip] = 1 - y[flip]
    x_train, _, y_train, _ = train_test_split(x, y, test_size=0.2, random_state=SEED, stratify=y)
    model = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000, random_state=SEED))
    model.fit(x_train, y_train)
    return model


def support_probability(model, attendance_pct, mst1_pct, assignment_pct):
    features = np.array([[attendance_pct, mst1_pct, assignment_pct]], dtype=float)
    return float(model.predict_proba(features)[0, 1])


def risk_label(probability):
    if probability >= 0.70:
        return "High"
    if probability >= 0.40:
        return "Moderate"
    return "Low"


def suggested_focus(attendance_pct, mst1_pct, assignment_pct):
    items = []
    if attendance_pct < 75:
        items.append("improve attendance")
    if mst1_pct < 40:
        items.append("revise MST1 topics")
    if assignment_pct < 40:
        items.append("complete assignments")
    return ", ".join(items) if items else "keep the current study routine"
