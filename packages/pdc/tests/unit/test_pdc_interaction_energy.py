from detergent_pdc.analysis.runs import interaction_energy


def test_the_three_receptor_pairs_sum_their_lj_and_coulomb_columns():
    labels = [
        'LJ-SR:Protein-Detergent', 'Coul-SR:Protein-Detergent',
        'LJ-SR:Protein-Protein', 'Coul-SR:Protein-Protein',
        'LJ-SR:Protein-Water', 'Coul-SR:Protein-Water',
    ]
    data = {
        'labels': labels,
        'times_ps': [0.0, 1000.0],
        'columns': [[-10.0, -20.0], [1.0, 2.0], [-5.0, -6.0], [-0.5, -1.0], [-30.0, -40.0], [0.0, 0.0]],
    }

    pairs = interaction_energy._pair_records(data)

    assert [pair['label'] for pair in pairs] == ['Receptor – detergent', 'Receptor only', 'Receptor – water']
    assert [pair['frames'] for pair in pairs] == [2, 2, 2]
    assert [pair['lj_sr_mean_kj_mol'] for pair in pairs] == [-15.0, -5.5, -35.0]
    assert [pair['coul_sr_mean_kj_mol'] for pair in pairs] == [1.5, -0.75, 0.0]
    assert [pair['total_mean_kj_mol'] for pair in pairs] == [-13.5, -6.25, -35.0]
    assert pairs[0]['series'] == {'time_ns': [0.0, 1.0], 'lj_sr_kj_mol': [-10.0, -20.0],
                                   'coul_sr_kj_mol': [1.0, 2.0], 'total_kj_mol': [-9.0, -18.0]}


def test_the_reported_terms_are_the_six_receptor_cross_terms():
    assert interaction_energy.TERMS == (
        'LJ-SR:Protein-Detergent', 'Coul-SR:Protein-Detergent',
        'LJ-SR:Protein-Protein', 'Coul-SR:Protein-Protein',
        'LJ-SR:Protein-Water', 'Coul-SR:Protein-Water')
