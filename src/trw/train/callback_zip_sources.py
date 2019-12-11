from trw.train import callback
import logging
import os
import zipfile
import pprint
import io


logger = logging.getLogger(__name__)


def zip_sources(roots, location, extensions):
    """
    Zip the content of `roots` folders with given extensions to a location
    """
    with zipfile.ZipFile(location, 'w') as f:
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                files = []
                for filename in filenames:
                    _, extension = os.path.splitext(filename)
                    if extension not in extensions:
                        continue
                    files.append(filename)

                for file in files:
                    full_path = os.path.join(dirpath, file)
                    f.write(full_path, arcname=os.path.relpath(full_path, root))


def default_extensions():
    return [
        # record python and configuration files
        '.py', '.sh', '.bat'
    ]


class CallbackZipSources(callback.Callback):
    """
    Record important info relative to the training such as the sources & configuration info

    This is to make sure a result can always be easily reproduced. Any configuration option
    can be safely appended in options['runtime']
    """
    def __init__(self, folders_to_record, extensions=default_extensions(), filename='sources.zip', max_width=200):
        if not isinstance(folders_to_record, list):
            folders_to_record = [folders_to_record]

        self.folders_to_record = folders_to_record
        self.extensions = extensions
        self.filename = filename
        self.max_width = max_width

    def __call__(self, options, history, model, losses, outputs, datasets, datasets_infos, callbacks_per_batch,
                 **kwargs):
        logging.info(f'CallbackZipSources, folders={self.folders_to_record}')
        source_zip_path = os.path.join(options['workflow_options']['current_logging_directory'], self.filename)
        zip_sources(self.folders_to_record, source_zip_path, extensions=self.extensions)

        stream = io.StringIO()
        pprint.pprint(options, stream=stream, width=self.max_width)
        logger.info(f'options=\n{stream.getvalue()}')

        logger.info('CallbackZipSources successfully done!')

