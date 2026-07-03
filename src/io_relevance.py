import pandas as pd


IO_TARGET_CATEGORIES = {
    "immune_checkpoint": {
        "PDCD1",
        "CD274",
        "PDCD1LG2",
        "CTLA4",
        "LAG3",
        "HAVCR2",
        "TIGIT",
        "VSIR",
        "CD276",
        "VTCN1",
    },
    "t_cell_activation": {
        "CD28",
        "ICOS",
        "TNFRSF9",
        "TNFRSF4",
        "TNFRSF18",
        "CD40",
        "CD40LG",
        "CD80",
        "CD86",
    },
    "myeloid_suppression": {
        "CSF1R",
        "CCR2",
        "CXCR2",
        "IL10",
        "TGFB1",
        "ARG1",
        "IDO1",
        "CD47",
        "SIRPA",
        "MRC1",
    },
    "antigen_presentation": {
        "B2M",
        "HLA-A",
        "HLA-B",
        "HLA-C",
        "TAP1",
        "TAP2",
        "JAK1",
        "JAK2",
        "IFNG",
        "STAT1",
    },
    "melanoma_driver_or_resistance": {
        "BRAF",
        "NRAS",
        "NF1",
        "PTEN",
        "CDKN2A",
        "MAP2K1",
        "MAP2K2",
        "MITF",
        "TERT",
        "TP53",
    },
}


CATEGORY_WEIGHTS = {
    "immune_checkpoint": 1.0,
    "t_cell_activation": 0.9,
    "myeloid_suppression": 0.9,
    "antigen_presentation": 0.8,
    "melanoma_driver_or_resistance": 0.5,
}


def annotate_io_relevance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add immuno-oncology relevance annotations to a target table.

    This first MVP uses a curated list of immuno-oncology and melanoma-resistance
    genes. Later versions should replace or extend this with literature mining,
    single-cell expression, spatial data, DepMap, and patient-response cohorts.
    """
    df = df.copy()

    categories = []
    scores = []

    for symbol in df["target_symbol"]:
        matched_categories = []

        for category, genes in IO_TARGET_CATEGORIES.items():
            if symbol in genes:
                matched_categories.append(category)

        if matched_categories:
            score = max(CATEGORY_WEIGHTS[cat] for cat in matched_categories)
            category_string = ";".join(matched_categories)
        else:
            score = 0.0
            category_string = "not_curated_io_target"

        categories.append(category_string)
        scores.append(score)

    df["io_category"] = categories
    df["immuno_oncology_score"] = scores

    return df
