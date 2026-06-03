from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2]
CSV_DIR = DATA_DIR / "csv"

DATAMART = CSV_DIR / "datamart.csv"
DATAMART_CMA_CGM = CSV_DIR / "datamart_cma_cgm.csv"

MAPPED_DATAMART_CMA_CGM = CSV_DIR / "mapped_datamart_cma_cgm.csv"
VALIDATION_RESULTS_CMA_CGM = CSV_DIR / "validation_results_cma_cgm.csv"
