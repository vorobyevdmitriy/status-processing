from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3]
CSV_DIR = DATA_DIR / "csv"

DATAMART_V4 = CSV_DIR / "datamartv4.csv"

MAPPED_EVENTS_CMA_CGM_V4 = CSV_DIR / "mapped_events_cma_cgm_v4.csv"
MAPPED_DATAMART_CMA_CGM_V4 = CSV_DIR / "mapped_datamart_cma_cgm_v4.csv"
MAPPED_CHAINS_CMA_CGM_V4 = CSV_DIR / "mapped_chains_cma_cgm_v4.csv"

AUTOMATON_RESULTS_CMA_CGM_V4 = CSV_DIR / "automaton_results_cma_cgm_mapped_v4.csv"
AUTOMATON_RESULTS_FAILED_L123_OR_SKIPPED_CMA_CGM_V4 = (
    CSV_DIR / "automaton_results_cma_cgm_failed_l123_or_skipped_v4.csv"
)
