.. _outputs:

==========================
Understanding the outputs
==========================

It's easy.


The `.h5` file
===============
The main output product is a HDF5_ `.h5` file.
This format has many viewers such as HDFView_ or HDFCompass_ and APIs such as Cpp_, FORTRAN_ and Python_.

.. image:: _static/output_main.png
   :width: 600

payload
---------
.. _payload-output:

.. image:: _static/output_payload.png
   :width: 600

The `payload` group contains all the information related to the instrument. Inside you will find a group for each channel
and a group called `payload description` containing the parsed `xml` payload description file.

.. image:: _static/output_channels.png
   :width: 600

Inside the `channels` group you will find a group for each channel called as the channel name.
In this case you have `Phot` and `Spec` as they are the channels contained in `payload_example.xml`.

Let's open a channel now.

.. image:: _static/output_spec.png
   :width: 600

Inside each channel you find a dataset that is called as the channel. This is the main channel output table.

.. image:: _static/output_spec_table.png
   :width: 600

Inside the text dataset called as the channel plus `_table_column_meta_` are contained the table metadata.
The couple dataset + metadata text can be read into an astropy quantity table (QTable_) with the function :func:`~exorad.output.hdf5.load`.
The `_to_group` directory contains the just described table converted into a dictionary and stored.

The `description` group contains the parsed section of the payload description file that contains the channel information.

Finally, the `built_instr` directory contains processed information related to the channel that allow ExoRad to load an
already built channel without initialize again the instrument.


target
---------
.. _target-output:

.. image:: _static/output_targets.png
   :width: 600

Inside the `targets` group you will find a directory for each target.

.. image:: _static/output_target.png
   :width: 600

Inside each target there will be a list of subdirectories containing everything that concerns the target.
For example you will find here all the information about the `foregrounds` and the `star`.
`skyTransmission` is the total transmission resulting from all the foregrounds.

The final results are stored in the `table` group.

.. image:: _static/output_target_table.png
   :width: 600

.. _QTable: https://docs.astropy.org/en/stable/api/astropy.table.QTable.html

.. _HDF5: https://www.hdfgroup.org/solutions/hdf5/

.. _HDFView: https://www.hdfgroup.org/downloads/hdfview/

.. _HDFCompass: https://support.hdfgroup.org/projects/compass/

.. _FORTRAN: https://support.hdfgroup.org/HDF5/doc/fortran/index.html

.. _Cpp: https://support.hdfgroup.org/HDF5/doc/cpplus_RM/index.html

.. _Python: https://www.h5py.org/