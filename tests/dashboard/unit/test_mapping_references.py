from dashboard.models.mappings.references import load_index
from tests.dashboard.fixtures import PROJECT_ROOT


def test_real_reference_records_have_verifiable_origins():
    index = load_index(PROJECT_ROOT)
    # Derive the expected ranks from the sources actually present: a partial
    # clone carries rank 1 only, and that is not a defect in the index.
    assert {record["source_rank"] for record in index["records"]} == {source["rank"] for source in index["sources"]}
    assert 1 in {source["rank"] for source in index["sources"]}
    assert {source["rank"] for source in index["sources"]} <= {1, 2, 3}
    assert all(record["fragment_id"] and record["references"] for record in index["records"])
    assert index["index_sha256"] == load_index(PROJECT_ROOT)["index_sha256"]


def test_specialized_source_precedes_generic_sources():
    index = load_index(PROJECT_ROOT)
    matches = [record for record in index["records"] if record["type"] == "SP4r"]
    assert matches and min(record["source_rank"] for record in matches) == 1
