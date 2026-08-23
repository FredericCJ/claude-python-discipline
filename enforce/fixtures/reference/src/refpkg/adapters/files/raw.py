"""Private persistent-representation seam owned by the files adapter.

The reference keeps this representation deliberately small. Its architectural
purpose is to give the ownership contract a real importable subject: clients may
reach file behavior through the port and adapter, never this private seam.
"""
