from pathlib import Path
import re
import os.path
import time
import random
import subprocess

import numpy as np
import pandas as pd
import nibabel as nib
import nilearn as nil
import scipy as sp
import pylab as pl

from numpy.testing.decorators import skipif
import mvpa2.suite as mvpa

# Get files
def get_files(dataset_dir, rglob_string):
    files = [str(Path("/").joinpath((Path(found_file).relative_to("/"))))
             for found_file in dataset_dir.rglob(rglob_string)]
    files = np.sort(files).tolist()
    return files


# Check if file/dir exists
def check_exi(path):
    path = Path(path)
    if path.exists():
        output = True
    else:
        output = False
    return output


# Check for file availability
def check_file_completeness(file_list):
    list_element = random.choice(file_list)
    if "ao" in list_element and len(file_list) == 112:
        output = True
    elif "av" in list_element and len(file_list) == 120:
        output = True
    elif "events" in list_element and len(file_list) == 8:
        output = True
    elif "warp" in list_element and len(file_list) == 15:
        output = True
    elif "roi" in list_element and len(file_list) == 7:
        output = True
    else:
        output = False
    return output


# Check if all components (directories, files, file_lists are complete)
def check_all_components(path_list, file_lists):
    path_exi_list = [
        check_exi(element)
        for element in path_list
    ]
    prob_paths_idx = [
        index
        for index, element in enumerate(path_exi_list)
        if element is False
    ]
    path_output = "All directories seem to be properly set up"
    if len(prob_paths_idx) != 0:
        path_output = [
            "This directory/file does not exist: {}".format(prob_ele)
            for prob_ele in path_list
            if path_list.index(prob_ele) in prob_paths_idx
        ]
    file_comp_list = [
        check_file_completeness(file_list)
        for file_list in file_lists
    ]
    prob_lists_idx = [
        index
        for index, element in enumerate(file_comp_list)
        if element is False
    ]
    lists_output = "All file lists seem to be complete"
    if len(prob_lists_idx) != 0:
        lists_output = [
            "This list is incomplete: {}".format(prob_ele[0])
            for prob_ele in file_lists
            if file_lists.index(prob_ele) in prob_lists_idx
        ]
    return path_output, lists_output


# Get participant + run number + stimulus type
def find_participant_info(ds_p):
    ds_p = str(ds_p)
    part_info = [ds_p[(ds_p.find("sub") + 4):(ds_p.find("sub") + 6)],
                 ds_p[(ds_p.find("movie") - 2):(ds_p.find("movie"))],
                 ds_p[(ds_p.find("run") + 4):(ds_p.find("run") + 5)]
                 ]
    return part_info

# Select only events after speaker change
def speaker_change(df, event_duration):
    bool_list1 = []
    bool_list2 = []

    run_end = df.iloc[-1]["onset"] + df.iloc[-1]["duration"]
    last_onset_to_include = run_end - event_duration

    # Speaker Change
    for idx in range(0, len(df)):
        if df.iloc[idx].loc["pos"] == "SENTENCE":
            if idx == 1:
                bool_list1.append(True)
            elif idx != 1:
                if df.iloc[idx].loc["person"] != df.iloc[idx - 1].loc["person"]:
                    bool_list1.append(True)
                else:
                    bool_list1.append(False)
        else:
            bool_list1.append(False)

    # Same Speaker with longer break
    sentence_list = df["pos"] == "SENTENCE"
    df["sentence_bool"] = sentence_list
    sentence_df = df[df['sentence_bool'] == True]

    idx_list = []
    for idx, row in sentence_df.iterrows():
        idx_list.append(idx)

    for idx, next_idx in zip(idx_list, idx_list[1:]):
        if idx == idx_list[0]:
            bool_list2.append([idx, True])

        if (next_idx == idx_list[-1] and
                df.iloc[idx].loc["person"] == df.iloc[next_idx].loc["person"] and
                (abs((df.iloc[idx].loc["onset"] + df.iloc[idx].loc["duration"]) -
                     df.iloc[next_idx].loc["onset"])) >= 2):
            bool_list2.append([idx, True])

        elif (df.iloc[idx].loc["person"] == df.iloc[next_idx].loc["person"] and
              (abs((df.iloc[idx].loc["onset"] + df.iloc[idx].loc["duration"]) -
                   df.iloc[next_idx].loc["onset"])) >= 2):
            bool_list2.append([idx, True])

        else:
            bool_list2.append([idx, False])

    # Change False in bool_list1 to True if True in bool_list2
    for arr, idx in zip(bool_list2, range(0, len(bool_list2))):
        if (bool_list1[arr[0]] != bool_list2[idx][1] and
                bool_list2[idx][1] == True):
            bool_list1[arr[0]] = True

    df['include'] = bool_list1
    df = df[df['include'] == True]
    df = df.iloc[:, 0:3]

    # exclude evs which don't allow full event duration
    ev_dur_bool_list = []
    for idx, row in df.iterrows():
        if row["onset"] < last_onset_to_include:
            ev_dur_bool_list.append(True)
        else:
            ev_dur_bool_list.append(False)

    df['ev_include'] = ev_dur_bool_list
    df = df[df['ev_include'] == True]
    df = df.iloc[:, 0:3]

    # change ev duration to specified time
    df["duration"] = event_duration

    return df

# Create event dict for the specific run of the individual dataset
def create_event_dict(anno_files_dir, ds_path, targets, event_duration, **kwargs):
    non_speech_evs = kwargs.get('non_speech_evs', True)
    non_speech_gap = kwargs.get('non_speech_gap', 2)

    part_info = find_participant_info(ds_path)

    # Speech Info
    anno_file = get_files(anno_files_dir, "*{}*{}*.tsv".format(part_info[1],
                                                                  part_info[2]))
    anno_info = pd.read_csv(anno_file[0], delimiter="\t", header=0)
    anno_info = speaker_change(anno_info, event_duration)

    events = anno_info.loc[anno_info["person"].isin(targets)]
    events = events.rename(columns={"person": "targets"})
    events_dict = events.to_dict(orient='records')

    # Non Speech Info
    if non_speech_evs:
        non_speech_info = pd.read_csv(anno_file[0], delimiter="\t", header=0)

        non_speech_list = []

        for [idx1, row1], [idx2, row2] in zip(non_speech_info.iterrows(),
                                              non_speech_info.iloc[1:, :].iterrows()):
            if (abs(row1["onset"] - row2["onset"]) > non_speech_gap):
                non_speech_list.append(row1["onset"] + non_speech_gap)

        for onset in non_speech_list:
            new_dict = {'onset': onset, 'duration': event_duration, 'targets': 'Non-Speech'}
            events_dict.append(new_dict)

    return events_dict


# Warp image to desired space
# change later so there is only one temp warped image
def warp_image(bold_file, ref_space, warp_file, output_path, **kwargs):
    save_disc_space = kwargs.get('save_disc_space', True)
    if save_disc_space:
        subprocess.call(['applywarp', '-r', ref_space, "-i", bold_file, "-o",
                         output_path, "-w", warp_file])
    elif save_disc_space == False and not os.path.isfile(output_path):
        subprocess.call(['applywarp', '-r', ref_space, "-i", bold_file, "-o",
                         output_path, "-w", warp_file])
    return output_path


# Find or generate fitting mask
def get_adjusted_mask(ori_mask, ref_space, **kwargs):
    overlap_mask = kwargs.get('overlap_mask', None)
    overlap = kwargs.get('overlap', "overlap")
    dilation = kwargs.get('dilation', False)
    side = kwargs.get('side', None)
    save_file = kwargs.get('save_file', False)

    ori_mask = str(ori_mask)
    ref_space = str(ref_space)

    if overlap_mask is not None:
        overlap_mask = str(overlap_mask)
        overlap_mask_p = str(overlap_mask)

    mask = nib.load(ori_mask)
    mask_affine = mask.affine
    mask_shape = mask.shape

    ref = nib.load(ref_space)
    ref_affine = ref.affine
    ref_shape = ref.shape

    if np.array_equal(mask_affine, ref_affine) and np.array_equal(mask_shape, ref_shape):
        new_mask = mask
        new_mask_p = ori_mask
        change = 0

        new_mask_data = mask.get_fdata()

        if dilation:
            new_mask_data = sp.ndimage.binary_dilation(new_mask_data)

        if side is not None:
            data = new_mask_data
            mean = len(data) / 2

            for idx, array in enumerate(data, 0):
                if side == "right" and idx > mean:
                    for idx1, mid_array in enumerate(data[idx], 0):
                        for idx2, end_array in enumerate(data[idx, idx1], 0):
                            data[idx, idx1, idx2] = False
                elif side == "left" and idx < mean:
                    for idx1, mid_array in enumerate(data[idx], 0):
                        for idx2, end_array in enumerate(data[idx, idx1], 0):
                            data[idx, idx1, idx2] = False
            new_mask_data = data

        if dilation or side is not None:
            new_mask_p = ori_mask[:-7]

            if dilation:
                new_mask_p = new_mask_p + "_dilation"

            if side is not None:
                new_mask_p = new_mask_p + "_{}".format(side)

            new_mask_p = new_mask_p + ".nii.gz"

        if overlap_mask is None:
            if dilation or side is not None:
                new_mask = nil.image.new_img_like(new_mask, new_mask_data, affine=ref_affine)
                if save_file:
                    nib.save(new_mask, new_mask_p)

    else:
        change = 1
        new_mask = nil.image.resample_img(mask, target_affine=ref_affine,
                                          target_shape=ref_shape, clip=True,
                                          interpolation="continuous")

        new_mask_data = new_mask.get_fdata()
        mask_mean = np.mean(new_mask_data)
        new_mask_data[new_mask_data >= mask_mean] = True
        new_mask_data[new_mask_data < mask_mean] = False
        new_mask_data[np.isnan(new_mask_data)] = False

        if dilation:
            new_mask_data = sp.ndimage.binary_dilation(new_mask_data)

        if side is not None:
            data = new_mask.get_fdata()
            mean = len(data) / 2

            for idx, array in enumerate(data, 0):
                if side == "right" and idx > mean:
                    for idx1, mid_array in enumerate(data[idx], 0):
                        for idx2, end_array in enumerate(data[idx, idx1], 0):
                            data[idx, idx1, idx2] = False
                elif side == "left" and idx < mean:
                    for idx1, mid_array in enumerate(data[idx], 0):
                        for idx2, end_array in enumerate(data[idx, idx1], 0):
                            data[idx, idx1, idx2] = False
            new_mask_data = data

        new_mask = nil.image.new_img_like(new_mask, new_mask_data, affine=ref_affine)

        if dilation or side is not None:
            new_mask_p = "{}_adjusted".format(ori_mask[:-7])

            if dilation:
                new_mask_p = new_mask_p + "_dilation"

            if side is not None:
                new_mask_p = new_mask_p + "_{}".format(side)

            new_mask_p = new_mask_p + ".nii.gz"
        else:
            new_mask_p = "{}_adjusted.nii.gz".format(ori_mask[:-7])

    if overlap_mask is None and change == 1:
        if save_file:
            nib.save(new_mask, new_mask_p)

    elif overlap_mask is not None:
        overlap_mask = nib.load(overlap_mask)
        overlap_mask_affine = overlap_mask.affine
        overlap_mask_shape = overlap_mask.shape

        if not np.array_equal(overlap_mask_affine, ref_affine) or not np.array_equal(overlap_mask_shape, ref_shape):
            overlap_mask = nil.image.resample_img(overlap_mask, target_affine=ref_affine,
                                                  target_shape=ref_shape, clip=True,
                                                  interpolation="continuous")
        mask_data = new_mask.get_fdata()
        mask_mean = np.mean(mask_data)
        mask_data[mask_data >= mask_mean] = True
        mask_data[mask_data < mask_mean] = False
        mask_data[np.isnan(mask_data)] = False

        overlap_mask_data = overlap_mask.get_fdata()
        overlap_mask_mean = np.mean(overlap_mask_data)
        overlap_mask_data[overlap_mask_data >= overlap_mask_mean] = True
        overlap_mask_data[overlap_mask_data < overlap_mask_mean] = False
        overlap_mask_data[np.isnan(overlap_mask_data)] = False

        if overlap == "overlap":
            for [idx1, top_array1], top_array2 in zip(enumerate(mask_data), overlap_mask_data):
                for [idx11, sub_array1], sub_array2 in zip(enumerate(top_array1), top_array2):
                    for [idx111, element1], element2 in zip(enumerate(sub_array1), sub_array2):
                        if element1 == True and element1 == element2:
                            mask_data[idx1, idx11, idx111] = True
                        else:
                            mask_data[idx1, idx11, idx111] = False
            result_data = mask_data

        elif overlap == "no overlap":
            for [idx1, top_array1], top_array2 in zip(enumerate(mask_data), overlap_mask_data):
                for [idx11, sub_array1], sub_array2 in zip(enumerate(top_array1), top_array2):
                    for [idx111, element1], element2 in zip(enumerate(sub_array1), sub_array2):
                        if element1 == element2:
                            mask_data[idx1, idx11, idx111] = False
            result_data = mask_data

        elif overlap == "combine":
            for [idx1, top_array1], top_array2 in zip(enumerate(mask_data), overlap_mask_data):
                for [idx11, sub_array1], sub_array2 in zip(enumerate(top_array1), top_array2):
                    for [idx111, element1], element2 in zip(enumerate(sub_array1), sub_array2):
                        if element1 or element2:
                            mask_data[idx1, idx11, idx111] = True
            result_data = mask_data

        if dilation:
            result_data = sp.ndimage.binary_dilation(result_data)

        new_mask = nil.image.new_img_like(new_mask, result_data, affine=ref_affine)

        if dilation or side is not None:
            new_mask_p = "{}_".format(ori_mask[:-7])

            if dilation:
                new_mask_p = new_mask_p + "_dilation"

            if side is not None:
                new_mask_p = new_mask_p + "_{}".format(side)

            new_mask_p = new_mask_p + "{}_overlap.nii.gz".format(overlap_mask_p.split("/")[-1].split("_", 1)[0])
        else:
            new_mask_p = "{}_{}.nii.gz".format(ori_mask[:-7], overlap_mask_p.split("/")[-1].split("_", 1)[0])

        if save_file:
            nib.save(new_mask, new_mask_p)
    if save_file:
        return new_mask_p
    else:
        return new_mask


# prepare roi info for ds
def prepare_roi_info(roi_mask_list):
    roi_dict = {}
    for roi_mask in roi_mask_list:
        key = "ROI - {}".format(roi_mask.split("/")[-1].split(",", 1)[0])
        roi_dict[key] = roi_mask
    return roi_dict


# fix array-like info after event extraction
def fix_info_after_events(ds):
    if type(ds.sa.chunks[0]) is np.ndarray:
        current_chunk_arr = ds.sa.chunks
        new_chunk_arr = [array[0] for array in current_chunk_arr]
        ds.sa["chunks"] = new_chunk_arr

    if type(ds.sa.participant[0]) is np.ndarray:
        current_part_arr = ds.sa.participant
        new_part_arr = [array[0] for array in current_part_arr]
        ds.sa["participant"] = new_part_arr

    if type(ds.sa.movie_type[0]) is np.ndarray:
        current_mov_arr = ds.sa.movie_type
        new_mov_arr = [array[0] for array in current_mov_arr]
        ds.sa["movie_type"] = new_mov_arr

    return ds

# Preprocess individual dataset
def preprocessing(ds_p, ref_space, warp_files, mask_p, **kwargs):
    mask_p = str(mask_p)
    ref_space = str(ref_space)
    detrending = kwargs.get('detrending', None)
    use_zscore = kwargs.get('use_zscore', True)

    use_events = kwargs.get('use_events', False)
    anno_dir = kwargs.get('anno_dir', None)
    use_glm_estimates = kwargs.get('use_glm_estimates', False)
    targets = kwargs.get('targets', None)
    event_offset = kwargs.get('event_offset', None)
    event_dur = kwargs.get('event_dur', None)
    save_disc_space = kwargs.get('save_disc_space', True)

    rois = kwargs.get('rois', None)

    vp_num_str = ds_p[(ds_p.find("sub") + 4):(ds_p.find("sub") + 6)]
    warp_file = [warp_file for warp_file in warp_files if warp_file.find(vp_num_str) != -1][0]
    part_info = find_participant_info(ds_p)

    if save_disc_space:
        temp_file_add = "tmp_warped_data_file.nii.gz"
        temp_file = str((Path.cwd().parents[0]).joinpath("data", "tmp", temp_file_add))
    else:
        temp_file_add = "sub-{}_{}-movie_run-{}_warped_file.nii.gz".format(part_info[0],
                                                                           part_info[1],
                                                                           int(part_info[2]))
        temp_file = str((Path.cwd().parents[0]).joinpath("data", "tmp",
                                                         "runs_for_testing",
                                                         temp_file_add)) # change

    warped_ds = warp_image(ds_p, ref_space, warp_file, temp_file, save_disc_space=save_disc_space)

    while not os.path.exists(warped_ds):
        time.sleep(5)

    if os.path.isfile(warped_ds):
        if mask_p is not None:
            mask = get_adjusted_mask(mask_p, ref_space)
            if rois is not None:
                ds = mvpa.fmri_dataset(samples=warped_ds, mask=mask, add_fa=rois)
            else:
                ds = mvpa.fmri_dataset(samples=warped_ds, mask=mask)
        else:
            if rois is not None:
                ds = mvpa.fmri_dataset(samples=warped_ds, add_fa=rois)
            else:
                ds = mvpa.fmri_dataset(samples=warped_ds)

    ds.sa['participant'] = [int(part_info[0])]
    ds.sa["movie_type"] = [part_info[1]]
    ds.sa['chunks'] = [int(part_info[2])]
    if detrending is not None:
        detrender = mvpa.PolyDetrendMapper(polyord=1)
        ds = ds.get_mapped(detrender)
    if use_zscore:
        mvpa.zscore(ds)
    if use_events:
        events = create_event_dict(anno_dir, ds_p, targets, event_dur)
        if use_glm_estimates:
            ds = mvpa.fit_event_hrf_model(ds, events, time_attr='time_coords',
                                          condition_attr='targets')

        else:
            ds = mvpa.extract_boxcar_event_samples(ds, events=events, time_attr='time_coords',
                                                   match='closest', event_offset=event_offset,
                                                   event_duration=event_dur, eprefix='event',
                                                   event_mapper=None)
            ds = fix_info_after_events(ds)
    return ds


# Preprocess multiple datasets
def preprocess_datasets(dataset_list, ref_space, warp_files, mask, **kwargs):
    detrending = kwargs.get('detrending', True)
    use_zscore = kwargs.get('use_zscore', True)

    use_events = kwargs.get('use_events', False)
    anno_dir = kwargs.get('anno_dir', None)
    use_glm_estimates = kwargs.get('use_glm_estimates', False)
    targets = kwargs.get('targets', None)
    event_offset = kwargs.get('event_offset', None)
    event_dur = kwargs.get('event_dur', None)
    save_disc_space = kwargs.get('save_disc_space', True)

    rois = kwargs.get('rois', None)

    if isinstance(dataset_list, list):
        datasets = [preprocessing(ds_p, ref_space, warp_files, mask, detrending=detrending,
                                  use_zscore=use_zscore, use_events=use_events, anno_dir=anno_dir,
                                  use_glm_estimates=use_glm_estimates, targets=targets,
                                  event_offset=event_offset, event_dur=event_dur, rois=rois,
                                  save_disc_space=save_disc_space)
                    for ds_p in dataset_list]

        if use_glm_estimates:
            for ds in datasets:
                del ds.sa["regressors"]

        ds = mvpa.vstack(datasets, a='drop_nonunique', fa='drop_nonunique')
    else:
        ds = preprocessing(dataset_list, ref_space, warp_files, mask, detrending=detrending,
                           use_zscore=use_zscore, use_events=use_events, anno_dir=anno_dir,
                           use_glm_estimates=use_glm_estimates, targets=targets,
                           event_offset=event_offset, event_dur=event_dur, rois=rois,
                           save_disc_space=save_disc_space)
    return ds


# Load or create and save ds
def load_create_save_ds(ds_save_p, dataset_list, ref_space, warp_files, mask, **kwargs):
    detrending = kwargs.get('detrending', True)
    use_zscore = kwargs.get('use_zscore', True)

    use_events = kwargs.get('use_events', False)
    anno_dir = kwargs.get('anno_dir', None)
    use_glm_estimates = kwargs.get('use_glm_estimates', False)
    targets = kwargs.get('targets', None)
    event_offset = kwargs.get('event_offset', None)
    event_dur = kwargs.get('event_dur', None)
    save_disc_space = kwargs.get('save_disc_space', True)

    rois = kwargs.get('rois', None)

    if ds_save_p.exists():
        ds = mvpa.h5load(str(ds_save_p))
    else:
        ds = preprocess_datasets(dataset_list, ref_space, warp_files, mask, detrending=detrending,
                                 use_zscore=use_zscore, use_events=use_events, anno_dir=anno_dir,
                                 use_glm_estimates=use_glm_estimates, targets=targets,
                                 event_offset=event_offset, event_dur=event_dur, rois=rois,
                                 save_disc_space=save_disc_space)
        mvpa.h5save(str(ds_save_p), ds) # , compression=9
    return ds

# Validation stuff
def num_same_event(ds, targets):
    list_ev_dicts = []
    for seg in np.unique(ds.sa.chunks):
        ev_dict = {}
        for person in np.unique(ds[ds.sa.chunks == seg].sa.targets):
            num = sum(1 for event in ds[ds.sa.chunks == seg].sa.targets
                      if event == person)
            key = "{}".format(person)
            ev_dict[key] = num
        for person in targets:
            key = "{}".format(person)
            if key not in ev_dict:
                ev_dict[key] = 0
        list_ev_dicts.append(ev_dict)
    df = pd.DataFrame(list_ev_dicts, index=range(1, len(np.unique(ds.sa.chunks))+1))
    return df

# Helper func to find correct indexes
def find_idx_pairs(df, pri_idx_array, sec_idx_array):
    data_list = [[abs(df.iloc[pri_idx].loc["onset"] + df.iloc[pri_idx].loc["duration"]
                      - df.iloc[sec_idx].loc["onset"]), pri_idx, sec_idx]
                 for pri_idx in pri_idx_array
                 for sec_idx in sec_idx_array]

    pair_list = []
    check_list = []
    find_mins = True

    while find_mins:
        data_diff_list = [element[0] for element in data_list]
        diff_min = np.amin(data_diff_list)
        min_idx = int(np.argwhere(data_diff_list == diff_min)[0])

        index1 = data_list[min_idx][1]
        index2 = data_list[min_idx][2]

        if index1 in check_list or index2 in check_list:
            data_list.pop(min_idx)

        if index1 not in check_list and index2 not in check_list:
            pair_list.append([index1, index2])
            check_list.extend([index1, index2])
            data_list.pop(min_idx)

        if not data_list:
            find_mins = False

    return pair_list


# duration of last event before speaker change has to be calculated in
def breaks_speaker(anno_files, targets, same_speaker):
    break_dict_list = []

    for anno_file in anno_files:
        break_dict = {}

        df = pd.read_csv(anno_file, delimiter="\t", header=0,
                         usecols=["onset", "duration", "person", "pos"])

        if same_speaker:
            for target in targets:
                all_rel_idx = [idx for idx in range(0, len(df))
                               if df.iloc[idx].loc["person"] == target]

                if all_rel_idx:
                    # last idx before new sentence, idx of next sentence
                    end_start_pairs = [[idx, next_index]
                                       for idx, next_index in zip(all_rel_idx, all_rel_idx[1:])
                                       if df.iloc[next_index].loc["pos"] == "SENTENCE"]

                    # onset of next sentence - (onset + duration) of last event before sentence
                    diff_list = [abs((df.iloc[pair[0]].loc["onset"]
                                      + df.iloc[pair[0]].loc["duration"])
                                     - df.iloc[pair[1]].loc["onset"])
                                 for pair in end_start_pairs]

                    break_dict[target] = diff_list
                else:
                    break_dict[target] = np.nan
        else:
            for pri_target in targets:

                pri_target_idx_first = [idx for idx in range(0, len(df))
                                        if df.iloc[idx].loc["person"] == pri_target
                                        if idx == 0 or idx > 0 and
                                        df.iloc[idx - 1].loc["person"] != pri_target]
                pri_target_idx_last = [idx for idx in range(0, len(df))
                                       if df.iloc[idx].loc["person"] == pri_target
                                       if idx < len(df) - 1 and
                                       df.iloc[idx + 1].loc["person"] != pri_target]

                for sec_target in targets:
                    if sec_target != pri_target:

                        key = "{} - {}".format(pri_target, sec_target)

                        sec_target_idx_first = [idx for idx in range(0, len(df))
                                                if df.iloc[idx].loc["person"] == sec_target
                                                if idx == 0 or idx > 0 and
                                                df.iloc[idx - 1].loc["person"] != sec_target]
                        sec_target_idx_last = [idx for idx in range(0, len(df))
                                               if df.iloc[idx].loc["person"] == sec_target
                                               if idx < len(df) - 1 and
                                               df.iloc[idx + 1].loc["person"] != sec_target]

                        if pri_target_idx_first and sec_target_idx_last:
                            pair_indexes1 = find_idx_pairs(df, pri_target_idx_first,
                                                           sec_target_idx_last)
                        else:
                            pair_indexes1 = []

                        if pri_target_idx_last and sec_target_idx_first:
                            pair_indexes2 = find_idx_pairs(df, pri_target_idx_last,
                                                           sec_target_idx_first)
                        else:
                            pair_indexes2 = []

                        pair_indexes1 = pair_indexes1 + pair_indexes2

                        if pair_indexes1:
                            diff_list = [abs((df.iloc[pair[0]].loc["onset"]
                                              + df.iloc[pair[0]].loc["duration"])
                                             - df.iloc[pair[1]].loc["onset"])
                                         for pair in pair_indexes1
                                         if pair]
                            break_dict[key] = diff_list
                        else:
                            break_dict[key] = np.nan

        max_list = []
        for k, v in break_dict.items():
            if isinstance(v, list):
                max_list.append(len(v))
            else:
                max_list.append(1)
        max_val = np.max(max_list)

        for k, v in break_dict.items():
            if isinstance(v, list):
                while len(v) < max_val:
                    break_dict[k].append(np.nan)
            else:
                break_dict[k] = [v]
                for x in range(0, (max_val - 1)):
                    break_dict[k].append(np.nan)

        break_df = pd.DataFrame(break_dict)
        break_dict_list.append(break_df)

    return break_dict_list

# RSA Result Visualization
def rsa_result_plot(mtx, labels, title):
    pl.figure()
    pl.imshow(mtx, interpolation='nearest')
    pl.xticks(range(len(mtx)), labels, rotation=-45)
    pl.yticks(range(len(mtx)), labels)
    pl.title(title)
    pl.clim((0, 2))
    pl.colorbar()