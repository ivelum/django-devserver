"""
Based on initial work from django-debug-toolbar
"""

from datetime import datetime
import sys
import traceback

import django
from django.db import connection
from django.db.backends import util
#from django.template import Node

from devserver.modules import DevServerModule
#from devserver.utils.stack import tidy_stacktrace, get_template_info
from devserver.utils.time import ms_from_timedelta
from devserver import settings

try:
    import sqlparse
except ImportError:
    class sqlparse:
        @staticmethod
        def format(text, *args, **kwargs):
            return text

# # TODO:This should be set in the toolbar loader as a default and panels should
# # get a copy of the toolbar object with access to its config dictionary
# SQL_WARNING_THRESHOLD = getattr(settings, 'DEVSERVER_CONFIG', {}) \
#                             .get('SQL_WARNING_THRESHOLD', 500)

class DatabaseStatTracker(util.CursorDebugWrapper):
    """
    Replacement for CursorDebugWrapper which outputs information as it happens.
    """
    logger = None
    
    def execute(self, sql, params=()):
        start = datetime.now()
        try:
            return self.cursor.execute(sql, params)
        finally:
            stop = datetime.now()
            duration = ms_from_timedelta(stop - start)
            # stacktrace = tidy_stacktrace(traceback.extract_stack())
            # template_info = None
            # # TODO: can probably move this into utils
            # cur_frame = sys._getframe().f_back
            # try:
            #     while cur_frame is not None:
            #         if cur_frame.f_code.co_name == 'render':
            #             node = cur_frame.f_locals['self']
            #             if isinstance(node, Node):
            #                 template_info = get_template_info(node.source)
            #                 break
            #         cur_frame = cur_frame.f_back
            # except:
            #     pass
            # del cur_frame
            
            try:
                sql = self.db.ops.last_executed_query(self.cursor, sql, params)
            except:
                sql = sql % params

            if self.logger:
                message = sqlparse.format(sql, reindent=True, keyword_case='upper')
            
                self.logger.debug(message, duration=duration)
                if self.cursor.rowcount >= 0:
                    self.logger.debug('Found %s matching rows', self.cursor.rowcount, duration=duration)
            
            self.db.queries.append({
                'sql': sql,
                'time': duration,
            })
            
    def executemany(self, sql, param_list):
        start = datetime.now()
        try:
            return self.cursor.executemany(sql, param_list)
        finally:
            stop = datetime.now()
            duration = ms_from_timedelta(stop - start)
            
            if self.logger:
                message = sqlparse.format(sql, reindent=True, keyword_case='upper')

                message = 'Executed %s times\n%s' % message
            
                self.logger.debug(message, duration=duration)
                self.logger.debug('Found %s matching rows', self.cursor.rowcount, duration=duration, id='query')
            
            self.db.queries.append({
                'sql': '%s times: %s' % (len(param_list), sql),
                'time': duration,
            })

class SQLRealTimeModule(DevServerModule):
    """
    Outputs SQL queries as they happen.
    """
    
    logger_name = 'sql/query'
    
    def process_init(self, request):
        if not isinstance(util.CursorDebugWrapper, DatabaseStatTracker):
            self.old_cursor = util.CursorDebugWrapper
            util.CursorDebugWrapper = DatabaseStatTracker
        DatabaseStatTracker.logger = self.logger
    
    def process_complete(self, request):
        if isinstance(util.CursorDebugWrapper, DatabaseStatTracker):
            util.CursorDebugWrapper = self.old_cursor

class SQLSummaryModule(DevServerModule):
    """
    Outputs a summary SQL queries.
    """
    
    logger_name = 'sql/summary'
    
    def process_complete(self, request):
        unique = set([s['sql'] for s in connection.queries])
        self.logger.info('%(calls)s queries with %(dupes)s duplicates' % dict(
            calls = len(connection.queries),
            dupes = len(connection.queries) - len(unique),
        ), duration=sum(float(c['time']) for c in connection.queries))
        