"""Real offline JPL/GeoNames integration smoke, no user records or charges."""

from bot.services.astro_chart_core import (
    build_karma_indicators,
    build_solar_return_facts,
    build_transit_snapshots,
)
from bot.services.astro_places import get_place


def main():
    source = get_place(498817)
    destination = get_place(2950159)
    birth = {
        'date': '29.02.2000', 'time': '13:45',
        'latitude': source['latitude'], 'longitude': source['longitude'],
        'timezone': source['timezone'],
    }
    karma = build_karma_indicators(birth)
    assert set(karma['indicators']) == {'TrueNode', 'MeanLilith', 'Saturn', 'Pluto'}
    print('KARMA_OK', len(karma['indicators']), flush=True)
    year = build_transit_snapshots(birth, year=2028)
    assert year['scope'] == 'year' and len(year['samples']) == 12
    print('YEAR_OK', len(year['samples']), flush=True)
    month = build_transit_snapshots(birth, year=2028, month=2)
    assert month['scope'] == 'month' and len(month['samples']) == 29
    assert month['samples'][0]['date'] == '2028-02-01'
    assert month['samples'][-1]['date'] == '2028-02-29'
    print('MONTH_OK', len(month['samples']), flush=True)
    destination_coords = {
        'latitude': destination['latitude'], 'longitude': destination['longitude'],
        'timezone': destination['timezone'],
    }
    solar = build_solar_return_facts(
        birth, target_year=2028, return_location=destination_coords,
    )
    chart = solar['solar_chart']
    assert len(chart['cusps']) == 12
    assert 'asc' in chart['angles'] and 'mc' in chart['angles']
    assert solar['return_location']['timezone'] == 'Europe/Berlin'
    assert len(chart['bodies']) == 12
    from bot.services.astro_chart_core import build_natal_facts
    sun_natal = build_natal_facts(birth)['chart']['bodies']['Sun']['lon']
    sun_solar = chart['bodies']['Sun']['lon']
    assert abs((sun_solar - sun_natal + 180) % 360 - 180) < 0.001
    print('SOLAR_OK', len(chart['cusps']), solar['solar_return_at_utc'], flush=True)
    from bot.services.astro_chart_core import AstroChartInputError
    try:
        build_solar_return_facts({**birth, 'time': None}, target_year=2028, return_location=destination_coords)
    except AstroChartInputError:
        print('SOLAR_UNKNOWN_BIRTH_TIME_REJECTED', flush=True)
    else:
        raise AssertionError('Solar calculated despite unknown birth time')


if __name__ == '__main__':
    main()
