"""

Creating/Editing existing annotations based on user selections of which structures should/shouldn't contain what other structures

"""

import os
import sys

import numpy as np

import json

import girder_client
from ctk_cli import CLIArgumentParser

import uuid

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid


def create_polygon_list(json_annotations:dict)->list:
    """
    Take large-image annotations and convert to list of polygon shapes.
    Includes holes.
    """
    poly_list = []
    for el_idx,el in enumerate(json_annotations['annotation']['elements']):
        #TODO: add rectangle and point annotations
        if el['type']=='polyline':
            el_coords = np.array(el['points'])
            x_y_tuples = [(i[0],i[1]) for i in el_coords.tolist()]

            if not 'holes' in el:
                hole_list = None
            else:
                hole_list = []
                for h in el['holes']:
                    hole_tuples = [(i[0],i[1]) for i in h]
                    hole_list.append(hole_tuples)

            el_poly = Polygon(x_y_tuples,holes = None)
            if el_poly.is_valid:
                poly_list.append(el_poly)
            else:
                # If the constructed polygon is invalid, use make_valid to make it valid.
                made_valid = make_valid(el_poly)
                if made_valid.geom_type=='Polygon':
                    if made_valid.is_valid:
                        poly_list.append(made_valid)
                elif made_valid.geom_type in ['MultiPolygon','GeometryCollection']:
                    for g in made_valid.geoms:
                        # Only add valid polygons to the list of polygons
                        if g.geom_type=='Polygon':
                            if g.is_valid:
                                poly_list.append(g)
    
    return poly_list

def make_annotation_from_shape(shape_list,name)->dict:
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
            hole_coords = list(shape.interiors)
            hole_list = []
            for h in hole_coords:
                hole_list.append([
                    [i[0],i[1],0]
                    for i in list(h.coords)
                ])

            annotation_dict['annotation']['elements'].append({
                'type': 'polyline',
                'points': [list(i)+[0] for i in coords],
                'holes': hole_list,
                'id': uuid.uuid4().hex[:24],
                'closed': True
            })

    return annotation_dict


def main(args):
    
    # Printing inputs from CLI
    for a in vars(args):
        print(f'{a}: {getattr(args,a)}')

    gc = girder_client.GirderClient(apiUrl = args.girderApiUrl)
    gc.setToken(args.girderToken)

    # Getting item Id from file
    image_item = gc.get(f'/file/{args.input_image}')['itemId']

    if not args.use_json:
        print(f'Running {args.ann_id_1} {args.operation} {args.ann_id_2} to create {args.new_name}')

        available_operations = ["+","-","plus","minus"]
        if not args.operation.lower() in available_operations:
            print(f'{args.operation} not implemented! :(')
            sys.exit(1)
        
        annotation_1 = gc.get(f'/annotation/{args.ann_id_1}?token={args.girderToken}')
        annotation_2 = gc.get(f'/annotation/{args.ann_id_2}?token={args.girderToken}')

        poly_list_1 = create_polygon_list(annotation_1)
        poly_list_2 = create_polygon_list(annotation_2)

        if args.operation.lower() in ["+","plus"]:
            # Addition of one annotation to another. (returns list of shapes)
            merged_annotations = unary_union(poly_list_1+poly_list_2)
            merged_list = merged_annotations.geoms

        elif args.operation.lower() in ["-","minus"]:
            # Subtraction of one annotation from another (returns one MultiPolygon)
            merged_annotations = MultiPolygon(poly_list_1).difference(MultiPolygon(poly_list_2))
            merged_list = merged_annotations.geoms

        # Creating new annotation from merged annotation geoms
        new_annotation = make_annotation_from_shape(merged_list,args.new_name)
        new_annotation_list = [new_annotation]

    else:
        # For more specific or multiple changes, passing json
        """
        Format should be like:
        json_spec = {
            "operations": [
                {
                    "new_name": "",
                    "ann_id_1": "",
                    "ann_id_2": "" (can also be comma separated but these are combined first and then the operation is applied)
                      if doing a (+/-) operation, otherwise ignored (properties aren't transferred after performing an operation),
                    "operation": + or - (as above) but also allows:
                        - "property": {
                            "key": name of property in "user",
                            "sub_key": if there's a sub-property to use,
                            "value": either a string if applying a categorical filter or a list [minimum, maximum]
                        }
                        - "within": {
                            "coordinates": [[x1,y1],...] exterior coordinates to include within
                        } <-- This could also be expanded to other spatial predicates ("intersects", "overlaps", etc. etc.)
                }
            ]
        }
        
        """
        json_operation = json.loads(args.json_spec)
        print(f'JSON operation: {json_operation}')

        new_annotation_list = []
        for op in json_operation['operations']:

            if op['operation'].lower() in ["+","-","plus","minus"]:
                if "," in op['ann_id_2']:
                    ann_id_2_list = op['ann_id_2'].split(',')
                    poly_list_2 = []
                    for a_2 in ann_id_2_list:
                        ann = gc.get(f'/annotation/{a_2}?token={args.girderToken}')
                        poly_list_2.extend(create_polygon_list(ann))
                elif not op['ann_id_2'] == "":
                    poly_list_2 = create_polygon_list(gc.get(f'/annotation/{op["ann_id_2"]}?token={args.girderToken}'))

                # Applying a + or - operation
                annotation_1 = gc.get(f'/annotation/{op["ann_id_1"]}?token={args.girderToken}')
                poly_list_1 = create_polygon_list(annotation_1)

                if op["operation"].lower() in ["+","plus"]:
                    # Addition of one annotation to another. (returns list of shapes)
                    merged_annotations = unary_union(poly_list_1+poly_list_2)
                    merged_list = merged_annotations.geoms

                elif op["operation"].lower() in ["-","minus"]:
                    # Subtraction of one annotation from another (returns one MultiPolygon)
                    merged_annotations = MultiPolygon(poly_list_1).difference(MultiPolygon(poly_list_2))
                    merged_list = merged_annotations.geoms

                # Creating new annotation from merged annotation geoms
                new_annotation = make_annotation_from_shape(merged_list,op['new_name'])
                new_annotation_list.append(new_annotation)

            elif op['operation'].lower()=='property':
                # Applying a filter by a property
                annotation = gc.get(f'/annotation/{op["ann_id_1"]}?token={args.girderToken}')
                property_filter = op['operation']['property']

                include_elements = []
                for el in annotation['annotation']['elements']:
                    if 'user' in el:
                        if property_filter['key'] in el['user']:
                            el_val = el['user'][property_filter['key']]
                            if 'sub_key' in property_filter:
                                if property_filter['sub_key'] in el_val:
                                    el_val = el_val[property_filter['sub_key']]
                            
                            if type(property_filter['value'])==str:
                                if el_val==property_filter['value']:
                                    new_id = uuid.uuid4().hex[:24]
                                    el['id'] = new_id
                                    include_elements.append(el)
                            if type(property_filter['value'])==list:
                                if el_val>=property_filter['value'][0] and el_val<=property_filter['value'][1]:
                                    new_id = uuid.uuid4().hex[:24]
                                    el['id'] = new_id
                                    include_elements.append(el)

                new_annotation = {
                    "annotation": {
                        "name": op['new_name'],
                        "elements": include_elements
                    }
                }

                new_annotation_list.append(new_annotation)

            elif op['operation'].lower()=='within':
                # Grabbing all annotations within a specified area and putting them in their own annotation
                annotation = gc.get(f'/annotation/{op["ann_id_1"]}?token={args.girderToken}')
                poly_list = create_polygon_list(annotation)

                # Creating the polygon shape from exterior coordinates provided in op
                filter_poly = Polygon([(i[0],i[1]) for i in op['operation']['within']['coordinates']])

                include_elements = []
                for i in range(len(poly_list)):
                    if poly_list[i].within(filter_poly):
                        new_id = uuid.uuid4().hex[:24]
                        annotation['annotation']['elements'][i]['id'] = new_id
                        include_elements.append(annotation['annotation']['elements'][i])

                new_annotation = {
                    "annotation": {
                        "name": op['new_name'],
                        "elements": include_elements
                    }
                }

                new_annotation_list.append(new_annotation)


    # Now adding the new annotation to the image
    if not args.test_run:

        for n in new_annotation_list:
            gc.post(f'/annotation/item/{image_item}?token={args.girderToken}',
                    data = json.dumps(n),
                    headers={
                        'X-HTTP-Method': 'POST',
                        'Content-Type':'application/json'
                    }
                )
    
    else:

        print(f'Creation of new annotations successful')
        for n in new_annotation_list:
            print(f'new annotation: {n["annotation"]["name"]} contains: {len(n["annotation"]["elements"])} elements')



if __name__=='__main__':
    main(CLIArgumentParser().parse_args())
