



def test_plotly_asset_is_local_and_fixed_path(dashboard):
    response = dashboard.client.get('/api/assets/plotly.min.js')

    assert response.status_code == 200
    assert response.mimetype == 'application/javascript'
    assert response.data.startswith(b'/*!') or b'Plotly' in response.data[:1000]


