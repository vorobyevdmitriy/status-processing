from src.src.mapping_runner import run_company_mapping
from src.src.config.paths import (
    DATAMART_V4,
    MAPPED_CHAINS_CMA_CGM_V4,
    MAPPED_DATAMART_CMA_CGM_V4,
    MAPPED_EVENTS_CMA_CGM_V4,
)


def main():
    run_company_mapping(
        company="CMA-CGM",
        input_path=str(DATAMART_V4),
        output_events=str(MAPPED_EVENTS_CMA_CGM_V4),
        output_datamart_like=str(MAPPED_DATAMART_CMA_CGM_V4),
        output_chains=str(MAPPED_CHAINS_CMA_CGM_V4),
    )


if __name__ == "__main__":
    main()
