"""Failed image/media preparation cannot enter the upload path."""
from unittest import TestCase
from unittest.mock import Mock, patch
from tools.ytbot import batch, channels


class BatchAssetFailure(TestCase):
    def setUp(self):
        # run_batch reads the channel cadence; keep the test independent of order.
        channels.apply("fallem-prince")

    def test_only_successfully_prepared_topics_reach_upload(self):
        topics = ['Image provider failed', 'Prepared video']
        with patch.object(batch.runtime, 'setup_profile'), patch.object(batch.runtime, 'start_hidden_chrome'), patch.object(batch, 'sync_playwright'), patch.object(batch.runtime, 'connect_hidden', return_value=(Mock(), Mock())), patch.object(batch.runtime, 'configure_downloads'), patch.object(batch.runtime, 'configure_extension'), patch.object(batch.account, 'ensure_channel'), patch.object(batch, '_refresh_catalog'), patch.object(batch.catalog, 'fetch_creator_videos', return_value={}), patch.object(batch, '_local_state', return_value=(set(), [])), patch.object(batch, 'prepare_topics', return_value=topics), patch.object(batch, '_asset_phase', return_value=[(topics[0], 'image provider failed')]), patch.object(batch.pipeline, 'upload_stage') as upload, patch.object(batch.logic, 'write_records_markdown'), patch.object(batch, '_summary'):
            failures = batch.run_batch(2, parallel=1)
        self.assertEqual(failures, [(topics[0], 'image provider failed')])
        upload.assert_called_once()
        self.assertEqual(upload.call_args.args[1], topics[1])
