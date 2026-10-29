"""A two-residue sugar must expose beads a name can identify.

The reference names sucrose's beads A/B/C/VS inside each of its two residues -- the fructofuranose that donates
the glycosidic bond and the glucose that receives it -- and lets the residue number distinguish the copies, which
is legal because GROMACS addresses atoms by index. Everything downstream of the catalogue keys beads by name
instead: the endpoint selections the panel sends, the PDB writer's serial map, and the viewer's index lookup. A
name used twice therefore addressed the first residue's atoms every time, which is why sucrose rendered as a
single ring with the second ring's bonds pointing into it, and why "the visualization is a bit strange" had no
symptom anywhere except the picture.
"""

from dashboard.models.compositions import catalog, topology

from tests.harness.support import PROJECT_ROOT

SOURCE = PROJECT_ROOT / 'references' / 'martini_v3.0.0_sugars_v2.itp'


def test_the_reference_really_does_repeat_the_names_it_is_asked_about():
    """The premise, read from the reference rather than assumed: sucrose has two residues sharing bead names."""
    sugars = topology.load_sugar_catalog(SOURCE)
    numbers = [atom["residue_number"] for atom in sugars["SUCR"]["atoms"]]
    assert sorted(set(numbers)) == [1, 2], numbers
    assert sugars["SUCR"]["name"] == "SUCR"


def test_a_repeated_bead_name_is_disambiguated_by_its_residue_number():
    """Sucrose is the case; every consumer that addresses a bead by name depends on this being unique."""
    sugars = topology.load_sugar_catalog(SOURCE)
    names = sugars["SUCR"]["bead_names"]
    assert len(set(names)) == len(names), names
    assert sorted(names) == ["A1", "A2", "B1", "B2", "C1", "C2", "VS1", "VS2"], names


def test_a_single_residue_sugar_keeps_the_reference_names():
    """Glucose has no ambiguity to resolve, so its beads stay exactly what the reference calls them."""
    sugars = topology.load_sugar_catalog(SOURCE)
    assert sugars["GLC"]["bead_names"] == ["A", "B", "C", "VS"]
    assert sugars["MAN"]["bead_names"] == ["A", "B", "C", "VS"]


def test_the_catalogue_offers_no_ambiguous_endpoint():
    """What the panel puts in its endpoint selectors is this list, so ambiguity here is what the user clicks."""
    choices = catalog()
    for sugar in choices["sugars"]:
        endpoints = sugar["endpoints"]
        assert len(set(endpoints)) == len(endpoints), sugar["id"]
        if sugar["id"] in ("LAC", "SUCR", "TREH"):
            assert len(endpoints) == 6, (sugar["id"], endpoints)


def test_the_two_ring_sugars_are_the_three_the_reference_defines():
    """The class this fixes: everything the reference maps as two residues, not just the one that was reported."""
    sugars = topology.load_sugar_catalog(SOURCE)
    two_residue = sorted(name for name, entry in sugars.items()
                         if len({atom["residue_number"] for atom in entry["atoms"]}) > 1)
    assert two_residue == ["LAC", "SUCR", "TREH"], two_residue
