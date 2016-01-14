# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##

from os.path import join as opj, exists, lexists
from datalad.tests.utils import with_tempfile, eq_, ok_, SkipTest

from ..annex import initiate_handle
from ..annex import Annexificator
from ....tests.utils import assert_equal, assert_in
from ....tests.utils import assert_raises
from ....tests.utils import with_tree, serve_path_via_http
from ....tests.utils import ok_file_under_git
from ....tests.utils import ok_file_has_content
from ...pipeline import load_pipeline_from_config
from ....consts import CRAWLER_META_CONFIG_PATH
from ....support.stats import ActivityStats

@with_tempfile(mkdir=True)
def test_initialize_handle(path):
    handle_path = opj(path, 'test')
    datas = list(initiate_handle('template', 'testhandle', path=handle_path)())
    assert_equal(len(datas), 1)
    data = datas[0]
    eq_(data['handle_path'], handle_path)
    crawl_cfg = opj(handle_path, CRAWLER_META_CONFIG_PATH)
    ok_(exists, crawl_cfg)
    pipeline = load_pipeline_from_config(crawl_cfg)
    raise SkipTest("TODO much more")


@with_tree(tree=[
    ('d1', (
        ('1.dat', '1.dat load'),
    ))
])
@serve_path_via_http()
@with_tempfile(mkdir=True)
def _test_annex_file(mode, topdir, topurl, outdir):
    annex = Annexificator(path=outdir, mode=mode, options=["-c", "annex.largefiles=exclude=*.txt"])

    input = {'url': "%sd1/1.dat" % topurl, 'filename': '1-copy.dat'}
    tfile = opj(outdir, '1-copy.dat')
    expected_output = [input.copy()]   # nothing to be added/changed
    output = list(annex(input))
    assert_equal(output, expected_output)
    ok_file_under_git(tfile, annexed=True)
    if mode == 'full':
        ok_file_has_content(tfile, '1.dat load')
    else:
        # in fast or relaxed mode there must not be any content
        assert_raises(AssertionError, ok_file_has_content, tfile, '1.dat load')
        assert(lexists(tfile))
    whereis = annex.repo.annex_whereis(tfile)
    assert_in("web", whereis)  # url must have been added
    assert_equal(len(whereis), 1 + int(mode=='full'))
    # TODO: check the url

    # Neither file should not be attempted to download again, since nothing changed
    # and by default we do use files db
    output = list(annex(input))
    assert_equal(output, [])  # nothing was done, so annex didn't yield data
    annex.yield_non_updated = True

    input_with_stats = input.copy()
    input_with_stats['datalad_stats'] = ActivityStats()
    output = list(annex(input_with_stats))
    assert_equal(output[0]['datalad_stats'], ActivityStats(files=1, urls=1, skipped=1))

    # but if we change that file, it should re-download it now
    with open(opj(topdir, 'd1', '1.dat'), 'a') as f:
        f.write("+")
    output = list(annex(input_with_stats))
    stats = output[0]['datalad_stats']
    stats.downloaded_time = 0
    # 2 since we are reusing the same stats
    download_stats = dict(downloaded=1, downloaded_size=11) if mode == 'full' else {}
    addskip_stats = dict(add_annex=0, skipped=2, overwritten=0) if mode == 'relaxed' else dict(add_annex=1, skipped=1, overwritten=1)
    kwargs = download_stats.copy()
    kwargs.update(addskip_stats)
    assert_equal(stats, ActivityStats(files=2, urls=2, **kwargs))

    # Download into a file which will be added to git
    input = {'url': "%sd1/1.dat" % topurl, 'filename': '1.txt', 'datalad_stats': ActivityStats()}
    tfile = opj(outdir, '1.txt')
    output = list(annex(input))
    annexed = mode not in {'full'}
    if not annexed:
        ok_file_has_content(tfile, '1.dat load+')
    else:
        # TODO: unfortunately we can't decide to add .txt without providing
        # our own parser for  annex.largefiles  ATM
        assert_raises(AssertionError, ok_file_has_content, tfile, '1.dat load+')
    ok_file_under_git(tfile, annexed=annexed)
    assert_equal(len(output), 1)
    stats = output[0]['datalad_stats']
    # reset varying metric
    stats.downloaded_time = 0
    assert_equal(stats, ActivityStats(files=1, urls=1, add_git=1-int(annexed), add_annex=int(annexed), **download_stats))


def test_annex_file():
    for mode in ('full', 'fast', 'relaxed',):
        yield _test_annex_file, mode

