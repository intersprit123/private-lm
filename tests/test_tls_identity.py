import tempfile
import unittest
from pathlib import Path
from windows_host.cluster_protocol import create_tls_identity

class TlsIdentityTests(unittest.TestCase):
    def test_self_signed_identity_and_fingerprint(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        with tempfile.TemporaryDirectory() as folder:
            cert_path, key_path, fingerprint = create_tls_identity(Path(folder), "192.168.1.22")
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            self.assertTrue(key_path.exists())
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual(fingerprint, cert.fingerprint(hashes.SHA256()).hex().upper())

if __name__ == "__main__":
    unittest.main()
