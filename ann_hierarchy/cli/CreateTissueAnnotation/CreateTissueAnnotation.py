"""

Plugin to create a tissue mask and add the exterior coordinates as an additional annotation

"""

import os
import sys

import numpy as np

import girder_client

from ctk_cli import CLIArgumentParser

from PIL import Image
from io import BytesIO
import requests

from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_holes
from skimage.measure import label, find_contours

import json
from shapely.geometry import Polygon
from shapely.validation import make_valid
from shapely.ops import unary_union
import uuid


def make_annotation_from_shape(shape_list,name,properties)->dict:
    """
    Take a Shapely shape object (MultiPolygon or Polygon or GeometryCollection) and return the corresponding annotation 
    """
    annotation_dict = {
        "annotation": {
            "name": name,
            "elements": []
        }
    }
    for shape in shape_list:
        
        if shape.geom_type=='Polygon' and shape.is_valid:
            # Exterior "shell" coordinates
            coords = list(shape.exterior.coords)
            """
            # Ignoring holes for tissue
            hole_coords = list(shape.interiors)
            hole_list = []
            for h in hole_coords:
                hole_list.append([
                    [i[0],i[1]]
                    for i in list(h.coords)
                ])
            """
            hole_list = []
            annotation_dict['annotation']['elements'].append({
                'type': 'polyline',
                'points': [list(i)+[0] for i in coords],
                'holes': hole_list,
                'id': uuid.uuid4().hex[:24],
                'closed': True,
                'user': properties
            })

    return annotation_dict

def main(args):
    
    # Printing inputs from CLI
    for a in vars(args):
        print(f'{a}: {getattr(args,a)}')

    gc = girder_client.GirderClient(apiUrl=args.girderApiUrl)
    gc.setToken(args.girderToken)

    # Getting item id from file
    image_item = gc.get(f'/file/{args.input_image}')['itemId']

    # Getting image information
    image_metadata = gc.get(f'/item/{image_item}/tiles')

    if not 'frames' in image_metadata:
        # Grabbing the thumbnail of the image (RGB)
        thumbnail_img = Image.open(BytesIO(requests.get(f'{gc.urlBase}/item/{image_item}/tiles/thumbnail?token={args.girderToken}').content))
        thumb_array = np.array(thumbnail_img)

    else:
        # Getting the max projection of the thumbnail
        thumb_frame_list = []
        for f in range(len(image_metadata['frames'])):
            thumb = Image.open(BytesIO(requests.get(f'{gc.urlBase}/item/{image_item}/tiles/thumbnail?frame={f}&token={args.girderToken}').content))
            thumb_frame_list.append(thumb)

        thumb_array = np.array(thumb_frame_list)

    # Getting scale factors for thumbnail image to full-size image
    thumbX, thumbY = np.shape(thumb_array)[1],np.shape(thumb_array)[0]
    scale_x = image_metadata['sizeX']/thumbX
    scale_y = image_metadata['sizeY']/thumbY
    
    
    # Making the whole thing grayscale
    if args.brightfield:
        thumb_array = 255-thumb_array

    # Mean of all channels/frames to make grayscale mask
    gray_mask = np.mean(thumb_array,axis=-1)

    if args.threshold==0:
        threshold_val = threshold_otsu(gray_mask)
        tissue_mask = gray_mask <= threshold_val

    else:
        threshold_val = args.threshold
        tissue_mask = gray_mask <= args.threshold

    print(f'threshold value: {threshold_val}, type: {type(threshold_val)}')
    print(np.sum(tissue_mask))
    tissue_mask = remove_small_holes(tissue_mask,area_threshold=150)

    labeled_mask = label(tissue_mask)
    tissue_pieces = np.unique(labeled_mask).tolist()
    print(tissue_pieces)
    tissue_shape_list = []
    for piece in tissue_pieces[1:]:
        tissue_contours = find_contours(labeled_mask==piece)

        for contour in tissue_contours:

            poly_list = [(i[1]*scale_x,i[0]*scale_y) for i in contour]
            if len(poly_list)>2:
                obj_polygon = Polygon(poly_list)

                if not obj_polygon.is_valid:
                    made_valid = make_valid(obj_polygon)

                    if made_valid.geom_type=='Polygon':
                        tissue_shape_list.append(made_valid)
                    elif made_valid.geom_type in ['MultiPolygon','GeometryCollection']:
                        for g in made_valid.geoms:
                            if g.geom_type=='Polygon':
                                tissue_shape_list.append(g)
                else:
                    tissue_shape_list.append(obj_polygon)

    # Merging shapes together to remove holes
    merged_tissue = unary_union(tissue_shape_list)
    if merged_tissue.geom_type=='Polygon':
        merged_tissue = [merged_tissue]
    elif merged_tissue.geom_type in ['MultiPolygon','GeometryCollection']:
        merged_tissue = merged_tissue.geoms

    annotation = make_annotation_from_shape(merged_tissue,'Tissue Mask',properties={'Threshold': threshold_val})

    if not args.test_run:
        # Posting tissue mask annotations
        gc.post(f'/annotation/item/{image_item}?token={args.girderToken}',
                data = json.dumps(annotation),
                headers={
                    'X-HTTP-Method': 'POST',
                    'Content-Type':'application/json'
                }
            )
    else:
        print(f'Creation of tissue mask annotation successful')
        print(f'Found: {len(annotation["annotation"]["elements"])} tissue pieces')


if __name__=='__main__':
    main(CLIArgumentParser().parse_args())



