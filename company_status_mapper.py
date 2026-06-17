from status_processing.cma_cgm.mapper import CmaCgmMapper
from status_processing.config.paths import (
    DATAMART_CMA_CGM,
    MAPPED_DATAMART_CMA_CGM,
)
from status_processing.mapping_runner import run_company_mapping


def main():
    run_company_mapping(
        company="CMA-CGM",
        input_path=str(DATAMART_CMA_CGM),
        output_events=None,
        output_datamart_like=str(MAPPED_DATAMART_CMA_CGM),
        output_chains=None,
        mapper=CmaCgmMapper(),
    )


if __name__ == "__main__":
    main()
