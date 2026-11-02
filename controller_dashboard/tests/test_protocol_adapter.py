import unittest
from controller_dashboard.protocol_adapter import normalize_protocol_rows

class ProtocolAdapterTests(unittest.TestCase):
    def test_mapping_and_dedupe(self):
        rows = [
            dict(task_id='42089', title='Поручение', document='ПР-032/25', group='ГД',
                 executor='Алексей\nБорис', planned_date='2025-05-05', closed_date='2025-05-06',
                 completed=True, status='Завершена', stage='Выполнены'),
            dict(task_id='42089', title='Поручение', completed=True),
            dict(task_id='8', title='Поручение без срока', completed=False, status='Выполняется'),
        ]
        items=normalize_protocol_rows(rows)
        self.assertEqual(len(items),2)
        self.assertEqual(items[0]['type'],'Протокол')
        self.assertFalse(items[0]['closed_on_time'])
        self.assertEqual(items[0]['executor_names'], ['Алексей','Борис'])
        self.assertEqual(items[1]['due'],'')
        self.assertIsNone(items[1]['controller_reaction'])

    def test_cancelled(self):
        x=normalize_protocol_rows([dict(task_id='1',status='Неактуально',completed=False)])
        self.assertEqual(x[0]['status'],'Неактуально')

if __name__ == '__main__':
    unittest.main()
