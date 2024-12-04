import os, sys
import requests
import argparse
import json
from datetime import datetime
from scipy.io import wavfile
from audiomentations.core.audio_loading_utils import load_sound_file
from audiomentations import AddBackgroundNoise, PolarityInversion


parser = argparse.ArgumentParser(description='Mix noise to audio files with SNR targets')
parser.add_argument('--noise-dir', type=str, required=True, help="Bucket path/prefix with noise files")
parser.add_argument('--audio-dir', type=str, required=True, help="Bucket path/prefix with audio/clean files")
parser.add_argument('--min-snr', type=float, required=True, help="Min SNR when mixing with noise files")
parser.add_argument('--max-snr', type=float, required=True, help="Max SNR when mixing with noise files")
parser.add_argument('--labelling-method', type=str, required=True, default="manual", help="Labelling method ('auto' will extract label from filename such as <label>.<rest-of-filename>.wav)")
parser.add_argument('--label', type=str, required=False, help="Label for the audio samples")
parser.add_argument('--upload-category', type=str, required=False, default="split", help="Which category to upload data to in Edge Impulse")
parser.add_argument('--synthetic-data-job-id', type=int, required=False, help="If specified, sets the synthetic_data_job_id metadata key")
parser.add_argument('--skip-upload', action="store_true", help="Skip uploading to EI")
parser.add_argument('--out-directory', type=str, required=False, default="output", help="Directory to save files to")
args, unknown = parser.parse_known_args()

if not args.skip_upload:
    if not os.getenv('EI_PROJECT_API_KEY'):
        print('Missing EI_PROJECT_API_KEY')
        sys.exit(1)
    else:
        API_KEY = os.environ.get("EI_PROJECT_API_KEY")

INGESTION_HOST = os.environ.get("EI_INGESTION_HOST", "edgeimpulse.com")
INGESTION_URL = "https://ingestion." + INGESTION_HOST
if (INGESTION_HOST.endswith('.test.edgeimpulse.com')):
    INGESTION_URL = "http://ingestion." + INGESTION_HOST
if (INGESTION_HOST == 'host.docker.internal'):
    INGESTION_URL = "http://" + INGESTION_HOST + ":4810"
    

output_folder = args.out_directory
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

noise_dir = args.noise_dir
audio_dir = args.audio_dir
# Check if directories exist
if not os.path.exists(noise_dir):
    print(f'Noise directory {noise_dir} not found')
    print('Directories under the bucket:', os.listdir('/mnt/s3fs/'))
    sys.exit(1)
if not os.path.exists(audio_dir):
    print(f'Audio directory {audio_dir} not found')
    print('Directories under the bucket:', os.listdir('/mnt/s3fs/'))
    sys.exit(1)

# Check SNR values
min_snr = args.min_snr
max_snr = args.max_snr
if min_snr > max_snr:
    print(f'min SNR ({min_snr} cannot be superior to max SNR ({max_snr}))')
    sys.exit(1)

labelling_method = args.labelling_method 
upload_category = args.upload_category
synthetic_data_job_id = args.synthetic_data_job_id

# Loop through audio files
for audio_file in os.listdir(audio_dir):

    if not audio_file.endswith('.wav'):
        print(f'Ignoring file {audio_file}, not a .wav file')
        continue

    audio_file_full_path = os.path.join(audio_dir, audio_file)

    # Define audio transformation function to mix background noise
    # One random noise file selected from noise_dir
    transform = AddBackgroundNoise(
        sounds_path=noise_dir,
        min_snr_db=min_snr,
        max_snr_db=max_snr,
        noise_transform=PolarityInversion(),
        p=1.0
    )

    print(f'Loading file {audio_file}...')

    # We load audio file as nparray and fix to 16 kHz, could be added as a parameter
    audio_samples, sr = load_sound_file(audio_file_full_path, sample_rate=16000, mono=True)

    # Mix noise to audio sample
    augmented_samples = transform(audio_samples, sample_rate=16000)

    # print mixed noise filename
    noise_file_path = transform.parameters["noise_file_path"]
    print(f'Mixing with noise file {noise_file_path} - min SNR={min_snr}dB, max SNR={max_snr}dB')

    noise_file_noext = os.path.splitext(os.path.basename(noise_file_path))[0]
    

    # Save to wavfile
    audio_file_noext = os.path.splitext(audio_file)[0]
    output_file = f'{audio_file_noext}_snr{min_snr}_{max_snr}_{noise_file_noext}.wav'
    output_file_path = os.path.join(output_folder, output_file)
    wavfile.write(output_file_path, rate=16000, data=augmented_samples)

    print(f'Generated {output_file} file.')

    generated_at = str(datetime.now())
 
    # Push new wav file to project
    if not args.skip_upload:

        # Assign label
        if labelling_method == 'auto':
            audio_file_label = audio_file.split('.')[0]
        else:
            if args.label is None:
                print('Labelling method set to manual but --label parameter not set')
                sys.exit(1)
            audio_file_label = args.label

        res = requests.post(url=INGESTION_URL + '/api/' + upload_category + '/files',
            headers={
                'x-label': audio_file_label,
                'x-api-key': API_KEY,
                'x-metadata': json.dumps({
                    'generated_by': 'mix-audio-generator',
                    'generated_at': generated_at,
                    'min_snr': str(min_snr),
                    'max_snr': str(max_snr),
                    'noise_file': noise_file_noext,
                    'clean_file': audio_file_noext
                }),
                'x-synthetic-data-job-id': str(synthetic_data_job_id) if synthetic_data_job_id is not None else None,
            },
            files = { 'data': (os.path.basename(output_file_path), open(output_file_path, 'rb'), 'audio/wav') }
        )
        if (res.status_code != 200):
            raise Exception(f'Failed to upload file to Edge Impulse (status_code={str(res.status_code)}): {res.content.decode("utf-8")}')
        else:
            body = json.loads(res.content.decode("utf-8"))
            if (body['success'] != True):
                raise Exception('Failed to upload file to Edge Impulse: ' + body['error'])
            if (body['files'][0]['success'] != True):
                raise Exception('Failed to upload file to Edge Impulse: ' + body['files'][0]['error'])
            print(f'file {output_file} pushed to Studio')

