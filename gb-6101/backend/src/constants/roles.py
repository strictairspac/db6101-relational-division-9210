from enum import StrEnum


class Role(StrEnum):
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    # Outsourced teams practise screening on drill copies only. They never see
    # original cases, run ids or vehicle numbers.
    OUTSOURCE = "outsource"
