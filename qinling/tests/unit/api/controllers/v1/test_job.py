# Copyright 2017 Catalyst IT Limited
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from datetime import datetime
from datetime import timedelta

from qinling import context as auth_context
from qinling.db import api as db_api
from qinling import status
from qinling.tests.unit.api import base


class TestJobController(base.APITest):
    def setUp(self):
        super(TestJobController, self).setUp()

        # Insert a function record in db for each test case. The data will be
        # removed automatically in db clean up.
        db_function = self.create_function()
        self.function_id = db_function.id

    def test_post(self):
        body = {
            'name': self.rand_name('job', prefix=self.prefix),
            'first_execution_time': str(
                datetime.utcnow() + timedelta(hours=1)),
            'function_id': self.function_id
        }
        resp = self.app.post_json('/v1/jobs', body)

        self.assertEqual(201, resp.status_int)

    def test_post_with_version(self):
        db_api.increase_function_version(self.function_id, 0)

        body = {
            'name': self.rand_name('job', prefix=self.prefix),
            'first_execution_time': str(
                datetime.utcnow() + timedelta(hours=1)),
            'function_id': self.function_id,
            'function_version': 1,
        }
        resp = self.app.post_json('/v1/jobs', body)

        self.assertEqual(201, resp.status_int)
        self.assertEqual(1, resp.json.get('function_version'))

    def test_post_pattern(self):
        body = {
            'name': self.rand_name('job', prefix=self.prefix),
            'function_id': self.function_id,
            'pattern': '0 21 * * *',
            'count': 10
        }
        resp = self.app.post_json('/v1/jobs', body)

        self.assertEqual(201, resp.status_int)

    def test_delete(self):
        job_id = self.create_job(
            self.function_id,
            first_execution_time=datetime.utcnow(),
            next_execution_time=datetime.utcnow() + timedelta(hours=1),
            status=status.RUNNING,
            count=1
        ).id

        resp = self.app.delete('/v1/jobs/%s' % job_id)

        self.assertEqual(204, resp.status_int)

    def test_update_one_shot_job(self):
        job_id = self.create_job(
            self.function_id,
            first_execution_time=datetime.utcnow(),
            next_execution_time=datetime.utcnow() + timedelta(hours=1),
            status=status.RUNNING,
            count=1
        ).id

        req_body = {
            'name': 'new_name',
            'status': status.PAUSED
        }
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

        req_body = {
            'status': status.RUNNING
        }
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

    def test_update_one_shot_job_failed(self):
        job_id = self.create_job(
            self.function_id,
            first_execution_time=datetime.utcnow(),
            next_execution_time=datetime.utcnow() + timedelta(hours=1),
            status=status.RUNNING,
            count=1
        ).id
        url = '/v1/jobs/%s' % job_id

        # Try to change job type
        resp = self.app.put_json(
            url,
            {'pattern': '*/1 * * * *'},
            expect_errors=True
        )

        self.assertEqual(400, resp.status_int)
        self.assertIn('Can not change job type.', resp.json['faultstring'])

        # Try to resume job but the execution time is invalid
        auth_context.set_ctx(self.ctx)
        self.addCleanup(auth_context.set_ctx, None)
        db_api.update_job(
            job_id,
            {
                'next_execution_time': datetime.utcnow() - timedelta(hours=1),
                'status': status.PAUSED
            }
        )
        resp = self.app.put_json(
            url,
            {'status': status.RUNNING},
            expect_errors=True
        )

        self.assertEqual(400, resp.status_int)
        self.assertIn(
            'Execution time must be at least 1 minute in the future',
            resp.json['faultstring']
        )

    def test_update_recurring_job(self):
        job_id = self.create_job(
            self.function_id,
            first_execution_time=datetime.utcnow() + timedelta(hours=1),
            next_execution_time=datetime.utcnow() + timedelta(hours=1),
            pattern='0 */1 * * *',
            status=status.RUNNING,
            count=10
        ).id

        req_body = {
            'next_execution_time': str(
                datetime.utcnow() + timedelta(hours=1.5)
            ),
            'pattern': '1 */1 * * *'
        }
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

        # Pause the job and resume with a valid next_execution_time
        req_body = {
            'status': status.PAUSED
        }
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

        req_body = {
            'status': status.RUNNING,
            'next_execution_time': str(datetime.utcnow() + timedelta(hours=2)),
        }
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

        # Pause the job and resume without specifying next_execution_time
        auth_context.set_ctx(self.ctx)
        self.addCleanup(auth_context.set_ctx, None)
        db_api.update_job(
            job_id,
            {
                'next_execution_time': datetime.utcnow() - timedelta(hours=1),
                'status': status.PAUSED
            }
        )

        req_body = {'status': status.RUNNING}
        resp = self.app.put_json('/v1/jobs/%s' % job_id, req_body)

        self.assertEqual(200, resp.status_int)
        self._assertDictContainsSubset(resp.json, req_body)

    def test_update_recurring_job_failed(self):
        job_id = self.create_job(
            self.function_id,
            first_execution_time=datetime.utcnow() + timedelta(hours=1),
            next_execution_time=datetime.utcnow() + timedelta(hours=1),
            pattern='0 */1 * * *',
            status=status.RUNNING,
            count=10
        ).id
        url = '/v1/jobs/%s' % job_id

        # Try to change job type
        resp = self.app.put_json(
            url,
            {'pattern': ''},
            expect_errors=True
        )

        self.assertEqual(400, resp.status_int)
        self.assertIn('Can not change job type.', resp.json['faultstring'])

        # Pause the job and try to resume with an invalid next_execution_time
        auth_context.set_ctx(self.ctx)
        self.addCleanup(auth_context.set_ctx, None)
        db_api.update_job(job_id, {'status': status.PAUSED})
        resp = self.app.put_json(
            url,
            {
                'status': status.RUNNING,
                'next_execution_time': str(
                    datetime.utcnow() - timedelta(hours=1)
                )
            },
            expect_errors=True
        )

        self.assertEqual(400, resp.status_int)
        self.assertIn(
            'Execution time must be at least 1 minute in the future',
            resp.json['faultstring']
        )
