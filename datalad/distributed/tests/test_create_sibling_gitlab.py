# ex: set sts=4 ts=4 sw=4 et:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Test create publication target on gitlab"""

import os

# this must import ok with and without gitlab
from datalad.api import (
    Dataset,
    create,
    create_sibling_gitlab,
)
from datalad.tests.utils_pytest import (
    assert_raises,
    assert_repo_status,
    assert_result_count,
    assert_status,
    eq_,
    with_tempfile,
)
from datalad.utils import chpwd


def _get_nested_collections(path):
    ds = Dataset(path).create()
    c1 = ds.create(ds.pathobj / 'subdir' / 'collection1')
    c1s1 = c1.create('sub1')
    c1s2 = c1.create('sub2')
    c2 = ds.create('collection2')
    c2s1 = c2.create('sub1')
    c2s11 = c2s1.create('deepsub1')
    ds.save(recursive=True)
    assert_repo_status(ds.path)
    # return a catalog
    return dict(
        root=ds,
        c1=c1,
        c1s1=c1s2,
        c1s2=c1s2,
        c2=c2,
        c2s1=c2s1,
        c2s11=c2s11,
    )


# doesn't actually need gitlab and exercises most of the decision logic
@with_tempfile
def test_dryrun(path=None):
    ctlg = _get_nested_collections(path)
    # no site config -> error
    assert_raises(ValueError, ctlg['root'].create_sibling_gitlab)
    # single project vs multi-dataset call
    assert_raises(
        ValueError,
        ctlg['root'].create_sibling_gitlab,
        site='site', project='one', recursive=True)
    assert_raises(
        ValueError,
        ctlg['root'].create_sibling_gitlab,
        site='site', project='one', path=['one', 'two'])
    # explicit cite, no path constraints, fails for lack of project path config
    res = ctlg['root'].create_sibling_gitlab(
        dry_run=True, on_failure='ignore',
        site='dummy',
    )
    assert_result_count(res, 1)
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='error',
        site='dummy', sibling='dummy',
    )
    # now a working, fully manual call
    for p in (None, ctlg['root'].path):
        res = ctlg['root'].create_sibling_gitlab(
            dry_run=True, on_failure='ignore',
            site='dummy', project='here',
            path=p,
        )
        assert_result_count(res, 1)
        assert_result_count(
            res, 1, path=ctlg['root'].path, type='dataset', status='ok',
            site='dummy', sibling='dummy', project='here',
        )

    # now configure a default gitlab site
    ctlg['root'].config.set('datalad.gitlab-default-site', 'theone')
    # we don't need to specify one anymore, but we can still customize
    # the sibling name
    res = ctlg['root'].create_sibling_gitlab(
        dry_run=True, on_failure='ignore',
        name='ursula', project='here',
    )
    assert_result_count(res, 1)
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='ok',
        site='theone', sibling='ursula', project='here',
    )
    # now configure a sibling name for this site
    ctlg['root'].config.set('datalad.gitlab-theone-siblingname', 'dieter')
    # and another one for another site
    ctlg['root'].config.set('datalad.gitlab-otherone-siblingname', 'ulf')
    # no need to specific 'name' anymore
    res = ctlg['root'].create_sibling_gitlab(
        dry_run=True, on_failure='ignore',
        project='here',
    )
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='ok',
        site='theone', sibling='dieter', project='here',
    )
    # properly switches the name based on site
    res = ctlg['root'].create_sibling_gitlab(
        dry_run=True, on_failure='ignore',
        site='otherone', project='here',
    )
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='ok',
        site='otherone', sibling='ulf', project='here',
    )
    # reports notneeded on existing='skip' with an existing remote
    ctlg['root'].repo.add_remote('dieter', 'http://example.com')
    res = ctlg['root'].create_sibling_gitlab(
        dry_run=True, on_failure='ignore',
        project='here', existing='skip',
    )
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='notneeded',
        site='theone', sibling='dieter',
    )
    ctlg['root'].repo.remove_remote('dieter')

    # lastly, configure a project path
    ctlg['root'].config.set('datalad.gitlab-theone-project', 'secret')
    # now we can drive it blind
    res = ctlg['root'].create_sibling_gitlab(dry_run=True)
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='ok',
        site='theone', sibling='dieter', project='secret',
    )
    # we can make use of the config in the base dataset to drive
    # calls on subdatasets: use -d plus a path
    res = ctlg['root'].create_sibling_gitlab(path='subdir', dry_run=True)
    # only a single result, doesn't touch the parent
    assert_result_count(res, 1)
    assert_result_count(
        res, 1, path=ctlg['c1'].path, type='dataset', status='ok',
        site='theone', sibling='dieter',
        # hierarchical setup: directories becomes groups
        # which implies each dataset is in its own group
        # project itself is placed at '_repo'_ to give URLs like
        # http://site/dir/dir/dir/_repo_.git
        # as a balance between readability and name conflict minimization
        project='secret/{}/_repo_'.format(
            ctlg['c1'].pathobj.relative_to(ctlg['root'].pathobj).as_posix()),
    )
    # we get the same result with an explicit layout request
    expl_res = ctlg['root'].create_sibling_gitlab(
        path='subdir', layout='hierarchy', dry_run=True)
    eq_(res, expl_res)
    # layout can be configured too, "collection" is "flat" in a group
    ctlg['root'].config.set('datalad.gitlab-theone-layout', 'collection')
    res = ctlg['root'].create_sibling_gitlab(
        path='subdir', dry_run=True)
    assert_result_count(
        res, 1, path=ctlg['c1'].path, type='dataset', status='ok',
        # http://site/group/dir--dir--dir--name.git
        project='secret/{}'.format(str(
            ctlg['c1'].pathobj.relative_to(ctlg['root'].pathobj)).replace(
                os.sep, '--')),
    )
    # make sure the reference dataset does not conflict with its group in this
    # case
    res = ctlg['root'].create_sibling_gitlab(dry_run=True)
    assert_result_count(
        res, 1, path=ctlg['root'].path, type='dataset', status='ok',
        project='secret/_repo_')
    # "flat" does GitHub-style
    ctlg['root'].config.set('datalad.gitlab-theone-layout', 'flat')
    res = ctlg['root'].create_sibling_gitlab(
        path='subdir', dry_run=True)
    assert_result_count(
        res, 1, path=ctlg['c1'].path, type='dataset', status='ok',
        # http://site/base--dir--dir--dir--name.git
        project='secret--{}'.format(str(
            ctlg['c1'].pathobj.relative_to(ctlg['root'].pathobj)).replace(
                os.sep, '--')),
    )

    # the results do not depend on explicitly given datasets, if we just enter
    # the parent dataset we get the same results
    with chpwd(str(ctlg['root'].pathobj / 'subdir')):
        rel_res = create_sibling_gitlab(path=os.curdir, dry_run=True)
        eq_(res, rel_res)
    # and again the same results if we are in a subdataset and point to a parent
    # dataset as a reference and config provider
    with chpwd(ctlg['c1'].path):
        rel_res = create_sibling_gitlab(
            dataset=ctlg['root'].path, path=os.curdir, dry_run=True)
        eq_(res, rel_res)

    # blows on unknown layout
    ctlg['root'].config.unset('datalad.gitlab-theone-layout')
    assert_raises(
        ValueError,
        ctlg['root'].create_sibling_gitlab, layout='funny', dry_run=True)

    # and finally recursion
    res = ctlg['root'].create_sibling_gitlab(recursive=True, dry_run=True)
    # one result per dataset
    assert_result_count(res, len(ctlg))
    # verbose check of target layout (easier to see target pattern for humans)
    # default layout: hierarchy
    eq_(
        sorted(r['project'] for r in res),
        [
            'secret',
            'secret/collection2/_repo_',
            'secret/collection2/sub1/_repo_',
            'secret/collection2/sub1/deepsub1/_repo_',
            'secret/subdir/collection1/_repo_',
            'secret/subdir/collection1/sub1/_repo_',
            'secret/subdir/collection1/sub2/_repo_',
        ]
    )
    res = ctlg['root'].create_sibling_gitlab(
        recursive=True, layout='collection', dry_run=True)
    assert_result_count(res, len(ctlg))
    eq_(
        sorted(r['project'] for r in res),
        [
            'secret/_repo_',
            'secret/collection2',
            'secret/collection2--sub1',
            'secret/collection2--sub1--deepsub1',
            'secret/subdir--collection1',
            'secret/subdir--collection1--sub1',
            'secret/subdir--collection1--sub2',
        ],
    )
    res = ctlg['root'].create_sibling_gitlab(
        recursive=True, layout='flat', dry_run=True)
    assert_result_count(res, len(ctlg))
    eq_(
        sorted(r['project'] for r in res),
        [
            'secret',
            'secret--collection2',
            'secret--collection2--sub1',
            'secret--collection2--sub1--deepsub1',
            'secret--subdir--collection1',
            'secret--subdir--collection1--sub1',
            'secret--subdir--collection1--sub2',
        ],
    )


class _FakeGitLab(object):
    def __init__(self, site):
        pass


class _NewProjectGitLab(_FakeGitLab):
    def get_project(self, path):
        return None

    def create_project(self, path, description=None):
        return dict(
            http_url_to_repo='http://example.com',
            ssh_url_to_repo='example.com',
            description=description,
        )


class _ExistingProjectGitLab(_FakeGitLab):
    def get_project(self, path):
        return dict(
            http_url_to_repo='http://example.com',
            ssh_url_to_repo='example.com',
        )


class _ExistingProjectOtherURLGitLab(_FakeGitLab):
    def get_project(self, path):
        return dict(
            http_url_to_repo='http://example2.com',
            ssh_url_to_repo='example2.com',
        )


class _CreateFailureGitLab(_FakeGitLab):
    def get_project(self, path):
        None

    def create_project(self, path, description=None):
        raise RuntimeError


@with_tempfile
def test_fake_gitlab(path=None):
    from unittest.mock import patch
    ds = Dataset(path).create()
    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite", _NewProjectGitLab):
        res = ds.create_sibling_gitlab(site='dummy', project='here', description='thisisit')
        assert_result_count(res, 2)
        # GitLab success
        assert_result_count(
            res, 1, action='create_sibling_gitlab', path=path, type='dataset',
            site='dummy', sibling='dummy', project='here', description='thisisit',
            project_attributes={
                'http_url_to_repo': 'http://example.com',
                'ssh_url_to_repo': 'example.com',
                'description': 'thisisit'
            },
            status='ok')
        assert_result_count(
            res, 1, action='configure-sibling', path=path, name='dummy',
            url='http://example.com', status='ok')

    # test sibling name conflicts
    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite", _ExistingProjectGitLab):
        res = ds.create_sibling_gitlab(path=ds.path, site='dummy',
                                       project='here', existing='skip')
        assert_result_count(res, 1)
        assert_result_count(
            res, 0, action='create_sibling_gitlab',
            message=['already has a configured sibling "%s"', "dummy"],
            path=path,
            refds=path,
            site='dummy', sibling='dummy',
            status='notneeded',
            type='dataset'
            )
    # sibling name conflict with existing='error' should yiel error
    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite", _ExistingProjectGitLab):
        res = ds.create_sibling_gitlab(path=ds.path, site='dummy',
                                       project='here', existing='skip')
        assert_result_count(res, 1)
        assert_result_count(
            res, 0, action='create_sibling_gitlab',
            message=['already has a configured sibling "%s"', "dummy"],
            path=path,
            refds=path,
            site='dummy', sibling='dummy',
            status='error',
            type='dataset'
            )
    # try recreation, the sibling is already configured, same setup, no error
    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite",
               _ExistingProjectGitLab):
        res = ds.create_sibling_gitlab(path=ds.path, site='dummy',
                                       project='here', existing='reconfigure')
        assert_result_count(
        res, 1, action='configure-sibling', path=path, name='dummy',
        url='http://example.com', status='ok')
        # but error when the name differs
        res = ds.create_sibling_gitlab(
            site='dummy', project='here', name='othername', on_failure='ignore')
        assert_result_count(res, 1)
        assert_result_count(
            res, 1, action='create_sibling_gitlab', path=path,
            site='dummy', sibling='othername', project='here',
            project_attributes={
                'http_url_to_repo': 'http://example.com',
                'ssh_url_to_repo': 'example.com'
            },
            status='error')

    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite", _CreateFailureGitLab):
        assert_status(
            'error',
            ds.create_sibling_gitlab(site='dummy', project='here', on_failure='ignore')
        )

    # new sibling, ssh access
    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite", _NewProjectGitLab):
        res = ds.create_sibling_gitlab(site='sshsite', project='here', access='ssh')
        assert_result_count(res, 2)
        assert_result_count(
            res, 1, action='create_sibling_gitlab', path=path, type='dataset',
            site='sshsite', sibling='sshsite', project='here',
            project_attributes={
                'http_url_to_repo': 'http://example.com',
                'ssh_url_to_repo': 'example.com',
                'description': None
            },
            status='ok')
        assert_result_count(
            res, 1, action='configure-sibling', path=path, name='sshsite',
            url='example.com', status='ok')

    with patch("datalad.distributed.create_sibling_gitlab.GitLabSite",
               _ExistingProjectOtherURLGitLab):
        res = ds.create_sibling_gitlab(site='sshsite', project='here',
                                       access='ssh', on_failure='ignore',
                                       name='sshsite2')
        assert_result_count(res, 1)
        assert_result_count(
            res, 0, action='create_sibling_gitlab',
            message=["There is already a project at '%s' on site '%s', "
                     "but no sibling with name '%s' is configured, "
                     "maybe use --existing=reconfigure", "here", "sshsite",
                     "sshsite2"],
            path=path,
            refds=path,
            site='sshsite', sibling='sshsite2', project='here',
            project_attributes={
                'http_url_to_repo': 'http://example2.com',
                'ssh_url_to_repo': 'example2.com'
            },
            status='error',
            type='dataset')
        # same goes for switching the access type without --reconfigure
        assert_status(
            'error',
            ds.create_sibling_gitlab(site='sshsite', project='here',
                                     access='http', on_failure='ignore')
        )
