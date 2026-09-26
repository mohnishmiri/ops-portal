from multicloud_diagrams import MultiCloudDiagrams
from utils.templating import TestRendering


class TestCoreVertexInIsolation(TestRendering):

    def test_list(self):
        # docs
        self.node_type = 'list'

        # given
        mcd = MultiCloudDiagrams()
        rows = [
            'IndexName',
            'IndexSizeBytes',
            'IndexStatus',
            'ItemCount',
            'RCU',
            'WCU',
        ]

        # when
        mcd.add_list(table_name='LSI:users_to_model-users-idx', rows=rows)

        # then
        expected = {
            'id': 'vertex:LSI:users_to_model-users-idx:list',
            'parent': '1',
            'style': 'swimlane;fontStyle=0;childLayout=stackLayout;horizontal=1;startSize=30;horizontalStack=0;'
                     'resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=1;marginBottom=0;whiteSpace=wrap;html=1;',
            'value': '<b>LSI:users_to_model-users-idx</b>',
            'vertex': '1'
        }
        expected_list = [
            {'id': '0'},
            {'id': '1', 'parent': '0'},
            {'id': 'vertex:LSI:users_to_model-users-idx:list',
             'parent': '1',
             'style': 'swimlane;fontStyle=0;childLayout=stackLayout;horizontal=1;startSize=30;horizontalStack=0;'
                      'resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=1;marginBottom=0;whiteSpace=wrap;html=1;',
             'value': '<b>LSI:users_to_model-users-idx</b>',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:0',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'IndexName',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:1',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'IndexSizeBytes',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:2',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'IndexStatus',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:3',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'ItemCount',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:4',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'RCU',
             'vertex': '1'},
            {'id': 'vertex:LSI:users_to_model-users-idx:row:5',
             'parent': 'vertex:LSI:users_to_model-users-idx:list',
             'style': 'text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;'
                      'overflow=hidden;portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;',
             'value': 'WCU',
             'vertex': '1'},
        ]
        self.verify_list(expected=expected, mx_file=mcd.mx_file, resource_name='LSI:users_to_model-users-idx', expected_list=expected_list)

        # docs
        self.mcd = mcd
